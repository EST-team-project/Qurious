"""자료 안내 시험 (TC-DG) — 「데이터 › 자료 안내」 1단계(설명 대장 → 생성물 → GET /api/data/guide → 화면 · 2026-10-08).

지키는 것 — 설계 03 문서 8.2절 시험 아이디어 다섯 + 연결 · 대장 점검
1. 생성물 = 대장 — `scripts/data_guide_scan.py --check` 가 통과하고, 줄 끝(CRLF)을 접어 견주며, 내용이 다르면 1 (TC-DG-01)
2. 수집 DB 의 모든 표가 안내에 있거나 「뺀 까닭」 이 있다 — 표 목록은 DB 를 열지 않고 백업 도구(TABLES · EXCLUDED)와
   표 속성 대장에서 · 숫자를 잇는 상태 열쇠는 상태가 세는 줄과 1 대 1 (TC-DG-02)
3. 일반 사용자 응답에 표 이름 · API 경로 · 명령 · 백업 이름이 글자로도 없다 — 서버가 싣지 않는다(관리자 응답이 대조군) (TC-DG-03)
4. 화면이 읽는 칸이 응답에 있다 — 화면 JS 가 「변수.칸」 으로 읽는 곳을 정규식으로 모아 응답과 맞댄다(TC-DH-03 꼴) (TC-DG-04)
5. 숫자가 없으면 설명만 — 0 을 넣지 않고 「없음」 · 상태가 예외면 까닭 · 상태가 늦으면 설명 · 백업 숫자를 먼저 (TC-DG-05 · 06)
6. 라우트 — 로그인 뒤 · 관리자 판정은 세션의 roles(다른 라우트와 같다) · 설명 파일이 없으면 503 (TC-DG-07)
7. 연결 — 메뉴(데이터 관제 바로 아래) · 뿌리 칸 · 모양 파일 · 진입 훅(글자 그대로) · 화면 스캐너 · 사용법 · 관리자 화면 셋 (TC-DG-08)
8. 대장 점검 — 쉬운 칸의 개발 말 · 모르는 출처 · 화면 · 머리 줄 · 점검에 걸리면 생성물을 쓰지 않는다 (TC-DG-09)

네트워크 · 실제 수집 DB 없이 돈다 — 상태(data_status.get_status)는 가짜로 바꾸고, 수집 폴더는 임시 폴더로 돌린다
(이 PC 의 수집 DB 는 앱이 읽기 전용으로 붙인 WAL DB 라 다른 프로세스가 열고 닫으면 앱이 멈출 수 있다 · DF-81).
글자를 찾는 시험은 주석에 속는다(2026-10-06 교훈) — 화면 JS 의 읽는 칸은 「변수.칸」 꼴만 모은다.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import data as data_routes
from app.services import collector_db
from app.services import data_guide as dg
from app.services import data_status as ds
from scripts import data_guide_scan as scan

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"

GROUPS = [{"key": "받기", "note": "출처에서 새 자료를 받는다"}, {"key": "계산", "note": "받은 자료로 새 표를 만든다"},
          {"key": "백업", "note": "Hugging Face 데이터셋으로 올린다"}, {"key": "근거 문서", "note": "근거 답이 쓰는 법령을 대조한다"}]
STEPS = [{"name": "price", "label": "시세", "group": "받기"}, {"name": "news", "label": "정책뉴스", "group": "받기"},
         {"name": "adjusted", "label": "수정주가", "group": "계산"}, {"name": "ohlcv", "label": "일봉", "group": "계산"},
         {"name": "export", "label": "내보내기", "group": "백업"}, {"name": "upload", "label": "올리기", "group": "백업"},
         {"name": "sector_laws", "label": "섹터 법령", "group": "근거 문서"}]


def _status(verdict: str = "ok", rows: int | None = 1000, rows_state: str = "fresh") -> dict:
    """가짜 상태 — 줄 열쇠 · 표 이름은 실제 상태 정의(data_status.TABLES)에서. 표 이름 칸까지 실어 응답으로 새지 않는지 본다."""
    missing = verdict == "missing"
    return {
        "checked_at": "2026-10-08T15:00:00+09:00", "as_of": "2021-10-07", "rows_state": rows_state,
        "runner": {"schedule": "매일 12:30", "running": False, "groups": GROUPS,
                   "last": {"started_at": "2026-10-08T12:30:01+09:00", "finished_at": "2026-10-08T13:25:00+09:00",
                            "minutes": 55.0, "ok": True,
                            "steps": [{**s, "status": "warning" if s["name"] == "news" else "ok", "rc": 0, "seconds": 1.0}
                                      for s in STEPS]}},
        "tables": [{"key": key, "table": table, "label": label, "group": grp, "source": src, "verdict": verdict,
                    "rows": 0 if missing else rows, "last_date": None if missing else "2021-10-07"}
                   for key, table, label, grp, src, *_ in ds.TABLES],
    }


def _hf_manifest() -> dict:
    def files(t: str, years: dict[str, int]) -> list[dict]:
        return [{"path": f"{t}/year={y}/part-00000.parquet", "rows": n, "bytes": 1} for y, n in years.items()]
    tables = {
        "price_daily": {"files": files("price_daily", {"2020": 600, "2021": 700})},
        "price_total_return": {"files": files("price_total_return", {"2020": 600, "2021": 700})},
        "disclosure": {"files": files("disclosure", {"2020": 100, "2021": 110})},
        "financial_statement": {"files": files("financial_statement", {"2019": 150, "2020": 200, "2021": 230})},
        "news_item": {"files": files("news_item", {"2020": 50, "2021": 60})},
        "corporate_action": {"files": [{"path": "corporate_action/corporate_action.parquet", "rows": 27, "bytes": 1}]},
        "intraday_universe": {"files": [{"path": "intraday_universe/intraday_universe.parquet", "rows": 801, "bytes": 1}]},
        "raw_response": {"files": [{"path": "raw_response/dart.parquet", "rows": 40, "bytes": 1},
                                   {"path": "raw_response/portal.parquet", "rows": 5, "bytes": 1}]},
        "ingest_day": {"files": [{"path": "ingest_day/ingest_day.parquet", "rows": 74, "bytes": 1}]},
    }
    return {"generated_at": "2026-10-08T13:23:09+09:00", "repo_id": "qurious-quant/krx-daily-market", "tables": tables}


def _ohlcv_manifest() -> dict:
    files = []
    for mk in ("KOSPI", "KOSDAQ", "KONEX", "ETF", "INDEX"):
        for basis in (("raw", "adj_base") if mk in ("KOSPI", "KOSDAQ", "KONEX") else ("raw",)):
            for tf in ("1d", "1w"):
                for y, first, last in (("2020", "2020-01-02", "2020-12-30"), ("2021", "2021-01-04", "2021-10-07")):
                    files.append({"path": f"ohlcv/timeframe={tf}/basis={basis}/market={mk}/year={y}/part-0.parquet",
                                  "rows": 100, "first": first, "last": last})
    for tf, first in (("60m", "2021-09-27"), ("5m", "2021-09-28")):
        files.append({"path": f"ohlcv/timeframe={tf}/basis=adj_split/year=2021/month=09/part-0.parquet",
                      "rows": 50, "first": first, "last": "2021-10-08"})
    return {"contract": "ohlcv-v1", "built_at": "2026-10-08T13:13:54+09:00", "as_of": "2021-10-07", "files": files}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """임시 수집 폴더(매니페스트 두 장 · 단계 목록) + 가짜 상태. 진짜 수집 DB · 기록 폴더로 가는 길을 막는다."""
    cdir = tmp_path / "data" / "collector"
    _write(cdir.parent / "hf_export" / "meta" / "manifest.json", _hf_manifest())
    _write(cdir / "ohlcv_export" / "manifest.json", _ohlcv_manifest())
    _write(cdir / "state" / ds.CATALOG_FILE, {"written_at": "2026-10-08T12:30:00+09:00", "groups": GROUPS, "steps": STEPS})
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(cdir / "market.sqlite3"))     # 없는 파일 — 진짜 수집 DB 를 열 길이 없다
    monkeypatch.setattr(ds, "collector_dir", lambda: cdir)
    box: dict = {"status": _status()}

    def fake_status():
        if isinstance(box["status"], Exception):
            raise box["status"]
        return box["status"]

    monkeypatch.setattr(ds, "get_status", fake_status)
    dg._status_job.update(thread=None, box=None)
    return SimpleNamespace(cdir=cdir, box=box)


def _collector_tables() -> set[str]:
    """수집 쪽 표 전부 — DB 를 열지 않고: 백업 도구의 TABLES · EXCLUDED + 표 속성 대장(DB = 수집)."""
    from scripts import hf_dataset
    return set(hf_dataset.TABLES) | set(hf_dataset.EXCLUDED) | scan.collector_tables(scan.read_attr())


# ── 1. 생성물 = 대장 ─────────────────────────────────────────────────────────
def test_generated_file_matches_ledgers(tmp_path):
    """TC-DG-01 · 생성물 = 대장 — --check 통과 · CRLF 로 체크아웃된 생성물도 같다 · 내용이 다르면 1 · 같은 대장이면 같은 바이트 ·
    앱이 읽는 파일이 곧 스캐너가 만드는 글이다 · 스캐너와 서비스는 수집 DB(SQLite)를 열지 않는다."""
    assert scan.main(["--check"]) == 0
    guide, problems = scan.build()
    assert problems == []
    made = scan.dumps(guide)
    assert scan.dumps(scan.build()[0]) == made                                   # 시각 같은 바뀌는 칸이 없다
    assert set(guide) == {"schema", "source", "groups", "sources", "items", "flow", "flow_notes", "tasks", "pitfalls", "excluded"}
    crlf = tmp_path / "guide.json"
    crlf.write_bytes(made.replace("\n", "\r\n").encode("utf-8"))
    assert scan.main(["--check", "--out", str(crlf)]) == 0                       # DF-77 꼴 — 줄 끝은 접어서 견준다
    stale = tmp_path / "stale.json"
    stale.write_bytes(made.replace('"주식 일봉"', '"주식 일봉(옛 이름)"', 1).encode("utf-8"))
    assert scan.main(["--check", "--out", str(stale)]) == 1
    assert scan.main(["--check", "--out", str(tmp_path / "없음.json")]) == 1
    assert dg.GUIDE_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n") == made
    for path in (ROOT / "scripts" / "data_guide_scan.py", ROOT / "app" / "services" / "data_guide.py"):
        assert not re.search(r"^\s*import sqlite3|^\s*from sqlite3", path.read_text(encoding="utf-8"), re.M), path.name


# ── 2. 수집 표가 빠짐없이 ─────────────────────────────────────────────────────
def test_every_collector_table_is_in_the_guide_or_excluded():
    """TC-DG-02 · 수집 DB 의 모든 표가 안내의 자료에 있거나 「뺀 까닭」 이 있다(백업의 TC-HF-01 과 같은 꼴) — 표 목록은 DB 를 열지
    않고 받는다. 안내가 잇는 표는 표 속성 대장에 있고, 숫자를 잇는 상태 열쇠는 상태가 세는 줄과 1 대 1 이다(모은 줄 합이 두 번
    세지 않고 빠지지도 않게). 판정 규칙은 합성 자료로도 잰다."""
    tables = _collector_tables()
    assert len(tables) >= 20, "백업 도구만 해도 수집 표 스물"
    guide = dg.load_guide()
    assert scan.coverage(guide, tables) == {"빠진_표": [], "까닭_없는_뺀_표": [], "안내와_뺀_표에_모두": []}
    attr = {r["표"] for r in scan.read_attr()}
    assert {t for it in guide["items"] for t in it["dev"]["tables"]} <= attr
    status_keys = [k for it in guide["items"] for k in it["stats_from"]["status"]]
    assert sorted(status_keys) == sorted(key for key, *_ in ds.TABLES)
    # 규칙 — 자료가 쓰지 않는 표 · 까닭 없이 뺀 표 · 쓰면서 뺀 표를 가린다
    fake = {"items": [{"dev": {"tables": ["a", "d"]}}], "excluded": [{"table": "b", "why": " "}, {"table": "d", "why": "까닭"}]}
    assert scan.coverage(fake, {"a", "b", "c", "d"}) == {"빠진_표": ["c"], "까닭_없는_뺀_표": ["b"], "안내와_뺀_표에_모두": ["d"]}


# ── 3. 일반 사용자 응답에 개발 칸이 없다 ─────────────────────────────────────────
#: 개발 말 — 표 이름은 따로(영문 · 숫자 · 밑줄에 붙지 않은 것). 스캐너의 쉬운 칸 규칙과 일부러 따로 적는다(한쪽이 틀려도 다른 쪽이 잡게).
DEV_PATTERNS = (
    r"/api/", r"(?<![A-Za-z0-9_])API-[A-Z]+-\d+", r"(?i)(?<![A-Za-z0-9_])python(?![A-Za-z0-9_])", r"(?<![A-Za-z0-9_])collector[./]",
    r"scripts/", r"\.sqlite3", r"\.parquet", r"Hugging Face", r"docs/",
    r"krx-daily-market|krx-ohlcv|dart-disclosure-financials|kb-legal-base|kb-sector-laws|qurious-quant",
)


def _leaks(text: str, tables: set[str]) -> list[str]:
    hits = [p for p in DEV_PATTERNS if re.search(p, text)]
    return hits + [t for t in sorted(tables) if re.search(rf"(?<![A-Za-z0-9_]){re.escape(t)}(?![A-Za-z0-9_])", text)]


def test_user_response_has_no_table_names_api_paths_or_commands(env):
    """TC-DG-03 · 일반 사용자 응답(JSON 글자 전체)에 표 이름 · API 경로 · API ID · 명령 · 백업 이름이 없다 — 서버가 싣지 않는다
    (CSS 로 숨기면 응답에는 남는다 · 결정 ①). 관리자 응답에는 같은 규칙에 걸리는 개발 칸이 있다(대조군 — 규칙이 헛돌지 않는다).
    일반 사용자의 「쓰는 화면」 · 「어디서」 에는 관리자 화면 셋이 없다."""
    tables = _collector_tables() | {t for it in dg.load_guide()["items"] for t in it["dev"]["tables"]}
    user = dg.read(admin=False)
    assert _leaks(json.dumps(user, ensure_ascii=False), tables) == []
    admin = dg.read(admin=True)
    found = _leaks(json.dumps(admin, ensure_ascii=False), tables)
    assert "price_daily" in found and "/api/" in found and r"(?i)(?<![A-Za-z0-9_])python(?![A-Za-z0-9_])" in found
    assert all("dev" in it for it in admin["guide"]["items"]) and "excluded" in admin["guide"] and "dev" in admin["stats"]
    assert all("dev" not in it and "stats_from" not in it for it in user["guide"]["items"])
    assert "excluded" not in user["guide"] and "dev" not in user["stats"]
    views = {v for it in user["guide"]["items"] for v in it["views"]} | {v for t in user["guide"]["tasks"] for v in t["views"]}
    assert not views & dg.ADMIN_VIEWS
    admin_views = {v for it in admin["guide"]["items"] for v in it["views"]}
    assert admin_views & dg.ADMIN_VIEWS, "대조군 — 관리자에게는 관리자 화면이 있다"


# ── 4. 화면이 읽는 칸 = 응답의 칸 ───────────────────────────────────────────────
#: 화면 JS 의 응답 변수(dataguide.js 머리말의 이름 규칙) — 「변수.칸.칸」 을 모은다
JS_READ = re.compile(r"(?<![\w.])(r|res|st|g|grp|it|s|src|run|lastRun|gx|fbox|fnote|task|pit|ear|mk)((?:\??\.[A-Za-z_]\w*)+)")


def _merged(objs: list[dict]) -> dict:
    """같은 꼴의 줄들을 칸 합집합 하나로 — 선택 칸(값이 None 인 줄이 있는 칸)은 값이 있는 줄의 값을 쓴다."""
    out: dict = {}
    for obj in objs:
        for k, v in obj.items():
            if out.get(k) is None:
                out[k] = v
    return out


def _missing(obj, chain: tuple[str, ...]) -> str | None:
    """칸 사슬대로 내려가 없는 칸 이름을 돌려준다. 목록 · 글자 · 숫자에 붙은 것(.map · .length · .startsWith)은 JS 의 것이라 멈춘다."""
    for key in chain:
        if not isinstance(obj, dict):
            return None
        if key not in obj:
            return key
        obj = obj[key]
    return None


def test_screen_reads_only_fields_the_server_sends(env):
    """TC-DG-04 · 화면이 읽는 칸이 응답에 있다 — dataguide.js 의 「변수.칸」 을 모두 모아 관리자 응답(칸이 가장 많다)과 맞댄다.
    서버가 칸 이름을 바꾸면 화면은 오류 없이 빈칸을 그린다(TC-DH-03 과 같은 까닭). 자료 숫자 상태의 화면 표 = 서버의 상태 열쇠."""
    admin = dg.read(admin=True)
    g, st = admin["guide"], admin["stats"]
    objs = {"r": [admin], "res": [admin], "st": [st], "g": [g], "grp": g["groups"], "it": g["items"],
            "s": list(st["items"].values()), "src": g["sources"], "run": [st["runner"]], "lastRun": [st["runner"]["last"]],
            "gx": st["runner"]["groups"], "fbox": g["flow"], "fnote": g["flow_notes"], "task": g["tasks"], "pit": g["pitfalls"],
            "ear": st["early"], "mk": [m for s in st["items"].values() for m in (s["markets"] or [])]}
    src = (PUB / "js" / "dataguide.js").read_text(encoding="utf-8")
    reads = {(m.group(1), tuple(re.findall(r"[A-Za-z_]\w*", m.group(2)))) for m in JS_READ.finditer(src)}
    assert len(reads) > 60, "화면이 읽는 칸을 거의 못 모았다 — 변수 이름 규칙(dataguide.js 머리말)을 볼 것"
    missing = []
    for var, chain in sorted(reads):
        assert objs[var], f"시험 자료에 {var} 줄이 없다 — 맞대 볼 수 없다"
        miss = _missing(_merged(objs[var]), chain)
        if miss:
            missing.append(f"{var}.{'.'.join(chain)} — 응답에 「{miss}」 칸이 없다")
    assert missing == []
    tone = re.search(r"const STATE_TONE = \{([^}]*)\}", src).group(1)
    assert set(re.findall(r"(\w+):", tone)) == set(dg.ITEM_WHY)
    assert {s["state"] for s in st["items"].values()} <= set(dg.ITEM_WHY)


# ── 5 · 6. 숫자가 없으면 설명만 ───────────────────────────────────────────────
def test_no_numbers_gives_descriptions_only(env):
    """TC-DG-05 · 숫자가 없으면 설명만 — 수집 DB 가 없는 PC(상태는 줄 수 0 · 「없음」, 매니페스트 없음)에서 설명 · 흐름 · 길잡이는 다
    오고 숫자 칸은 None(말없이 0 을 넣지 않는다) · 까닭이 달린다. 상태가 예외면 설명은 그대로 · 「읽지 못했습니다」 ·
    관리자에게는 까닭. 표가 없어도 백업 목록이 있으면 연도별은 오고 줄 수 칸은 「일부」 로 까닭을 단다."""
    env.box["status"] = _status(verdict="missing")
    hf = env.cdir.parent / "hf_export" / "meta" / "manifest.json"
    ohlcv = env.cdir / "ohlcv_export" / "manifest.json"
    hf.unlink()
    ohlcv.unlink()
    out = dg.read(admin=False)
    g, st = out["guide"], out["stats"]
    assert len(g["items"]) == len(dg.load_guide()["items"]) and all(it["name"] and it["line"] for it in g["items"])
    assert g["tasks"] and g["pitfalls"] and g["flow"] and g["sources"]
    assert st["available"] is False and "모은 자료가 없습니다" in st["note"]
    assert st["total_rows"] is None and st["first"] is None and st["years"] == []
    for key, s in st["items"].items():
        assert s["rows"] is None and s["last"] is None and not s["years"], key
        assert s["state"] in ("none", "no_link") and s["why"], key
    # 상태가 예외 — 설명은 그대로 · 까닭을 단다(관리자에게는 무엇이 터졌는지)
    env.box["status"] = RuntimeError("잠김")
    out = dg.read(admin=True)
    assert out["stats"]["problems"] == ["자료 상태를 읽지 못했습니다"] and "읽지 못했습니다" in out["stats"]["note"]
    assert any("RuntimeError" in p for p in out["stats"]["dev"]["problems"])
    assert len(out["guide"]["items"]) == len(g["items"])
    assert out["stats"]["items"]["stock-day"]["state"] == "error"
    # 표는 없고 백업 목록만 있는 PC — 연도별은 오고 줄 수는 「일부」 · 까닭
    env.box["status"] = _status(verdict="missing")
    _write(hf, _hf_manifest())
    _write(ohlcv, _ohlcv_manifest())
    s = dg.read(admin=False)["stats"]["items"]["stock-day"]
    assert s["rows"] is None and s["years"] == {"2020": 300, "2021": 300} and s["state"] == "partial" and s["why"]


def test_slow_status_sends_descriptions_first(env, monkeypatch):
    """TC-DG-06 · 상태 계산이 기다림 한도를 넘으면(캐시가 빈 뒤 컨테이너 9 ~ 20초) 설명 · 백업 목록 숫자를 먼저 보내고
    (status_pending) 상태 칸은 「세는 중」 — 계산은 뒤에서 끝까지 돌고, 다음 요청은 그 결과를 쓴다. 겹쳐 띄우지 않는다."""
    gate = threading.Event()
    calls = []

    def slow():
        calls.append(1)
        gate.wait(5)
        return _status(rows=1234)

    monkeypatch.setattr(ds, "get_status", slow)
    monkeypatch.setattr(dg, "STATUS_WAIT_SECONDS", 0.05)
    out = dg.read(admin=False)
    st = out["stats"]
    assert st["status_pending"] is True and "세는 중" in st["note"] and st["total_state"] == "counting"
    s = st["items"]["stock-day"]
    assert s["rows"] is None and s["state"] == "counting" and s["years"] == {"2020": 300, "2021": 300}
    assert out["guide"]["items"] and out["guide"]["tasks"]
    dg.read(admin=False)                                      # 도는 계산이 있으면 새로 띄우지 않는다
    assert len(calls) == 1
    gate.set()
    dg._status_job["thread"].join(5)
    st = dg.read(admin=False)["stats"]
    assert st["status_pending"] is False and st["items"]["stock-day"]["rows"] == 1234 and st["note"] == ""


# ── 7. 라우트 ────────────────────────────────────────────────────────────────
def test_route_login_admin_split_and_missing_file(env, monkeypatch):
    """TC-DG-07 · GET /api/data/guide — 로그인 뒤(쿠키 없으면 401) · 모든 로그인 사용자 200 · 관리자 판정은 세션의 roles
    (다른 데이터 라우트의 `_require_admin` 과 같은 방법) · 설명 생성물이 없으면 503 과 까닭."""
    app = FastAPI()
    app.include_router(data_routes.router)
    c = TestClient(app)
    assert c.get("/api/data/guide").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}
    u = c.get("/api/data/guide")
    assert u.status_code == 200 and u.json()["viewer"] == {"admin": False}
    assert all("dev" not in it for it in u.json()["guide"]["items"])
    app.dependency_overrides[get_current_user] = lambda: {"id": "a1", "roles": ["user", "admin"]}
    a = c.get("/api/data/guide").json()
    assert a["viewer"] == {"admin": True} and all("dev" in it for it in a["guide"]["items"])
    monkeypatch.setattr(dg, "GUIDE_PATH", env.cdir / "없는-설명.json")
    monkeypatch.setitem(dg._guide_cache, "sig", None)
    r = c.get("/api/data/guide")
    assert r.status_code == 503 and "설명 파일" in r.json()["detail"]


# ── 8. 연결 ──────────────────────────────────────────────────────────────────
def test_menu_root_assets_hook_and_scanner():
    """TC-DG-08 · 연결 — 「데이터」 묶음의 데이터 관제 바로 아래 · 뿌리 칸(관제와 수집 화면 셋 사이) · 모양 파일 · 진입 훅(글자 그대로) ·
    화면 스캐너가 읽는 진입 API · 사용법 한 줄. 모든 로그인 사용자 화면이라 일반 사용자 메뉴에서 숨기지 않고, 화면 JS 는 관리자 여부로
    칸을 숨기지 않는다(서버가 싣는 것만 그린다). 서버의 관리자 화면 셋 = collect.css 가 일반 사용자에게서 숨기는 셋."""
    core = (PUB / "js" / "core.js").read_text(encoding="utf-8")
    html = (PUB / "app.html").read_text(encoding="utf-8")
    main = (PUB / "js" / "main.js").read_text(encoding="utf-8")
    src = (PUB / "js" / "dataguide.js").read_text(encoding="utf-8")
    crawl = core[core.index("  crawl: {"):core.index("  trading: {")]
    assert re.findall(r'\{ key: "([^"]+)"', crawl)[:2] == ["data-status", "data-guide"]
    assert re.search(r'\{ key: "data-guide",\s*icon: "[^"]+",\s*label: "자료 안내" \}', crawl)
    assert '<div class="view" data-view="data-guide"><div class="dg-root"></div></div>' in html
    assert html.index('data-view="data-status"') < html.index('data-view="data-guide"') < html.index('data-view="crawl-auto"')
    assert 'href="/css/dataguide.css"' in html and (PUB / "css" / "dataguide.css").is_file()
    assert re.search(r'^import \{ onDataGuideViewActivated \} from "/js/dataguide\.js";', main, re.M)
    assert re.search(r"^\s+onDataGuideViewActivated\(view\);", main, re.M)
    assert '"data-guide":' in core[core.index("const VIEW_GUIDES"):]
    assert 'if (view !== "data-guide") return;' in src
    from scripts import view_scan
    entry = {r["key"]: set(r["entry_apis"]) for r in view_scan.scan()["rows"]}
    assert entry["data-guide"] == {"/api/data/guide"}
    css = (PUB / "css" / "collect.css").read_text(encoding="utf-8")
    assert 'data-view="data-guide"' not in css and 'data-menu-view="data-guide"' not in css
    assert set(re.findall(r'body:not\(\.q-admin\) \.lnb-item\[data-view="([^"]+)"\]', css)) == set(dg.ADMIN_VIEWS)
    assert "q-admin" not in src and "getMe" not in src


# ── 9. 대장 점검 ─────────────────────────────────────────────────────────────
def test_ledger_checks_catch_bad_rows(tmp_path, monkeypatch, capsys):
    """TC-DG-09 · 대장 점검 — 쉬운 칸의 표 이름 · API 경로, 출처 대장에 없는 출처, app.html 에 없는 화면, 표 속성 대장에 없는 표,
    머리 줄이 다른 대장을 가린다. 점검에 걸리면 생성물을 쓰지 않고 종료코드 1(말없이 빠지는 줄이 없게)."""
    d = tmp_path / "대장"
    d.mkdir()
    for fname, _cols in scan.LEDGERS.values():
        shutil.copy(scan.LEDGER_DIR / fname, d / fname)
    assert scan.build(d)[1] == []
    p = d / "자료안내-자료.tsv"
    text = p.read_text(encoding="utf-8")
    text = text.replace("국내 상장 주식의 하루 시세 — 원 가격", "price_daily 표의 하루 시세 — /api/data/ohlcv", 1)
    text = text.replace("trading-chart · robo-rebalance", "trading-chart · no-such-view", 1)
    text = text.replace("\tfsc\t", "\tnosuch\t", 1)
    text = text.replace("\tbenchmark_index\t", "\tghost_table\t", 1)
    p.write_text(text, encoding="utf-8")
    problems = "\n".join(scan.build(d)[1])
    assert "stock-day.한줄 — 쉬운 칸에 API 경로" in problems and "쉬운 칸에 표 이름 price_daily" in problems
    assert "「no-such-view」 — app.html 에 그런 화면이 없다" in problems
    assert "「nosuch」 — 출처 대장에 없다" in problems
    assert "「ghost_table」 — 표 속성 대장에 없다" in problems
    (d / "자료안내-뺀표.tsv").write_text("표\t이유\r\n", encoding="utf-8")
    assert any("자료안내-뺀표.tsv 머리 줄" in x for x in scan.build(d)[1])
    # 점검에 걸리면 쓰지 않는다
    monkeypatch.setattr(scan, "build", lambda *a, **k: ({}, ["시험용 까닭"]))
    out = tmp_path / "새-생성물.json"
    assert scan.main(["--write", "--out", str(out)]) == 1 and not out.exists()
    assert "시험용 까닭" in capsys.readouterr().out
