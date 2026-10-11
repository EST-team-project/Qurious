"""자료 안내 시험 (TC-DG) — 「데이터 › 자료 안내」 1단계(설명 대장 → 생성물 → GET /api/data/guide → 화면 · 2026-10-08) ·
2단계(칸 정의 · 러너가 회차마다 쓰는 숫자 파일 · 2026-10-11).

지키는 것 — 설계 03 문서 8.2절 시험 아이디어 다섯 + 연결 · 대장 점검 + 2단계 둘
1. 생성물 = 대장 — `scripts/data_guide_scan.py --check` 가 통과하고, 줄 끝(CRLF)을 접어 견주며, 내용이 다르면 1 (TC-DG-01)
2. 수집 DB 의 모든 표가 안내에 있거나 「뺀 까닭」 이 있다 — 표 목록은 DB 를 열지 않고 백업 도구(TABLES · EXCLUDED)와
   표 속성 대장에서 · 숫자를 잇는 상태 열쇠는 상태가 세는 줄과 1 대 1 (TC-DG-02)
3. 일반 사용자 응답에 표 이름 · 칸 이름 · 열쇠 · API 경로 · 명령 · 백업 이름이 글자로도 없다 — 서버가 싣지 않는다
   (관리자 응답이 대조군) (TC-DG-03)
4. 화면이 읽는 칸이 응답에 있다 — 화면 JS 가 「변수.칸」 으로 읽는 곳을 정규식으로 모아 응답과 맞댄다(TC-DH-03 꼴) (TC-DG-04)
5. 숫자가 없으면 설명만 — 0 을 넣지 않고 「없음」 · 숫자 파일이 없거나 옛 판 · 깨졌으면 까닭 (TC-DG-05)
6. 요청 때 세지 않는다 — 숫자는 러너가 쓴 파일에서만 읽는다(상태 계산 · 수집 DB 를 막아도 답한다) · 수집이 도는 중 ·
   수집 뒤 못 씀의 안내 줄 (TC-DG-06 · 2026-10-11 결정 ④ 를 다 지킴 — 1단계의 「늦으면 설명 먼저」 를 바꿈)
7. 라우트 — 로그인 뒤 · 관리자 판정은 세션의 roles(다른 라우트와 같다) · 설명 파일이 없으면 503 (TC-DG-07)
8. 연결 — 메뉴(데이터 관제 바로 아래) · 뿌리 칸 · 모양 파일 · 진입 훅(글자 그대로) · 화면 스캐너 · 사용법 · 관리자 화면 셋 (TC-DG-08)
9. 대장 점검 — 쉬운 칸의 개발 말 · 칸 이름 · 모르는 출처 · 화면 · 칸 · 단위 · 머리 줄 · 점검에 걸리면 생성물을 쓰지 않는다 (TC-DG-09)
10. 칸 정의 = 코드의 칸 — 안내가 잇는 표의 모든 칸에 쉬운 이름 · 단위 · 뜻이 하나씩(빠짐 0 · 남음 0) · 칸 차례 · 열쇠는 코드
    CREATE 문 그대로 · 칸 정의를 만들 때 수집 DB 를 열지 않는다 (TC-DG-10)
11. 쓰는 쪽 → 읽는 쪽 한 줄 — 러너의 숫자 함수가 실제 SQLite 를 세어 쓴 파일을 자료 안내가 그대로 읽는다(DF-102 교훈) (TC-DG-11)

네트워크 · 실제 수집 DB 없이 돈다 — 숫자 파일 · 러너 기록은 임시 폴더에 가짜로 쓰고, 상태 계산(data_status.get_status ·
table_states)은 부르면 실패하게 막는다(이 PC 의 수집 DB 는 앱이 읽기 전용으로 붙인 WAL DB 라 다른 프로세스가 열고 닫으면
앱이 멈출 수 있다 · DF-81). 글자를 찾는 시험은 주석에 속는다(2026-10-06 교훈) — 화면 JS 의 읽는 칸은 「변수.칸」 꼴만 모은다.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import datetime
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


#: 마지막 회차 기록(러너가 쓰는 꼴) — 정책뉴스 단계는 멈추지 않는 실패(rc 3)라 흐름 상자에 「확인할 단계」 가 붙는다
LAST = {"started_at": "2026-10-08T12:30:01+09:00", "finished_at": "2026-10-08T13:25:00+09:00", "ok": False, "upload": True,
        "steps": [{**s, "fatal": s["name"] != "news", "rc": 3 if s["name"] == "news" else 0, "seconds": 1.0} for s in STEPS]}
#: 숫자 파일을 쓴 때 — 마지막 회차가 끝난 뒤(정상)
WRITTEN = "2026-10-08T13:25:30+09:00"


def _numbers(rows: int | None = 1000, missing: bool = False, written_at: str = WRITTEN, schema: int = 1) -> dict:
    """가짜 숫자 파일 — 러너가 회차 끝에 쓰는 꼴(표 열쇠는 실제 상태 정의 data_status.TABLES 에서 · 셈법 한 곳)."""
    return {"schema": schema, "written_at": written_at, "by": "run", "seconds": 1.2,
            "tables": [{"key": key, "rows": None if missing else rows, "last_date": None if missing else "2021-10-07",
                        "missing": missing} for key, *_ in ds.TABLES]}


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


#: 진짜 셈법 — 픽스처가 막기 전에 잡아 둔다(TC-DG-11 은 러너 쪽에서 진짜로 센다)
_REAL_TABLE_STATES = ds.table_states


def _no_counting(*_a, **_k):
    raise AssertionError("자료 안내는 요청 때 세지 않는다 — 숫자는 러너가 쓴 파일에서만(결정 ④)")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """임시 수집 폴더(매니페스트 두 장 · 단계 목록 · 마지막 회차 · 숫자 파일). 진짜 수집 DB · 기록 폴더로 가는 길을 막고,
    상태 계산(get_status · table_states · 줄 수 세기)은 부르면 실패한다 — 자료 안내가 요청 때 세면 모든 시험이 깨진다."""
    cdir = tmp_path / "data" / "collector"
    _write(cdir.parent / "hf_export" / "meta" / "manifest.json", _hf_manifest())
    _write(cdir / "ohlcv_export" / "manifest.json", _ohlcv_manifest())
    _write(cdir / "state" / ds.CATALOG_FILE, {"written_at": "2026-10-08T12:30:00+09:00", "groups": GROUPS, "steps": STEPS})
    _write(cdir / "state" / "daily_update_last.json", LAST)
    _write(cdir / "state" / dg.NUMBERS_FILE, _numbers())
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(cdir / "market.sqlite3"))     # 없는 파일 — 진짜 수집 DB 를 열 길이 없다
    monkeypatch.setattr(ds, "collector_dir", lambda: cdir)
    for name in ("get_status", "table_states", "start_count", "_connect_ro"):
        monkeypatch.setattr(ds, name, _no_counting)
    return SimpleNamespace(cdir=cdir, state=cdir / "state", numbers=cdir / "state" / dg.NUMBERS_FILE)


def _collector_tables() -> set[str]:
    """수집 쪽 표 전부 — DB 를 열지 않고: 백업 도구의 TABLES · EXCLUDED + 표 속성 대장(DB = 수집)."""
    from scripts import hf_dataset
    return set(hf_dataset.TABLES) | set(hf_dataset.EXCLUDED) | scan.collector_tables(scan.read_attr())


# ── 1. 생성물 = 대장 ─────────────────────────────────────────────────────────
def test_generated_file_matches_ledgers(tmp_path, monkeypatch):
    """TC-DG-01 · 생성물 = 대장 — --check 통과 · CRLF 로 체크아웃된 생성물도 같다 · 내용이 다르면 1 · 같은 대장이면 같은 바이트 ·
    앱이 읽는 파일이 곧 스캐너가 만드는 글이다 · 스캐너와 서비스는 수집 DB(SQLite)를 열지 않는다 — 칸 정의(2단계)는 코드
    CREATE 문 · 앱 모델에서 읽으므로 sqlite3.connect 를 막아도 생성물이 같다."""
    assert scan.main(["--check"]) == 0
    from scripts import schema_scan

    def no_db(*_a, **_k):
        raise AssertionError("칸 정의를 만들며 수집 DB 를 열었다 — 코드 CREATE 문에서 읽어야 한다(DF-81)")

    monkeypatch.setattr(schema_scan.sqlite3, "connect", no_db)
    guide, problems = scan.build()
    assert problems == []
    assert guide["schema"] == scan.SCHEMA == dg.SCHEMA == 2, "칸 정의가 들어간 판 — 앱과 스캐너가 같은 판을 안다"
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
    # 칸 정의(2단계) — 칸 이름 · 타입 · 열쇠는 관리자 답에만(결정 ② · 2026-10-11 「열쇠 표시는 관리자에게만」)
    a_cols = [c for it in admin["guide"]["items"] if it["columns"] for g in it["columns"]["tables"] for c in g["cols"]]
    u_cols = [c for it in user["guide"]["items"] if it["columns"] for g in it["columns"]["tables"] for c in g["cols"]]
    assert a_cols and all(set(c["dev"]) == {"col", "type", "key"} for c in a_cols), "대조군 — 관리자에게는 칸 이름 · 타입 · 열쇠"
    assert any(c["dev"]["key"] for c in a_cols)
    assert u_cols and all(set(c) == {"name", "unit", "text"} for c in u_cols), "일반 사용자 칸 줄은 쉬운 이름 · 단위 · 뜻만"
    assert all("dev" not in g for it in user["guide"]["items"] if it["columns"] for g in it["columns"]["tables"])
    snake = sorted({c["dev"]["col"] for c in a_cols if "_" in c["dev"]["col"]})
    assert len(snake) > 100, "칸 이름 대조군이 너무 적다"
    # 설명(guide) 쪽만 본다 — 숫자(stats)에는 우리 응답 칸 이름(as_of · first_year …)이 있어, 같은 꼴의 칸 이름(섹터 법령의 as_of)을
    # 샘으로 잘못 센다(2026-10-11 첫 판이 그렇게 실패했다)
    text = json.dumps(user["guide"], ensure_ascii=False)
    assert [s for s in snake if re.search(rf"(?<![A-Za-z0-9_]){re.escape(s)}(?![A-Za-z0-9_])", text)] == []
    assert "열쇠" not in json.dumps(user, ensure_ascii=False), "열쇠 표시 · 설명 줄은 관리자에게만"


# ── 4. 화면이 읽는 칸 = 응답의 칸 ───────────────────────────────────────────────
#: 화면 JS 의 응답 변수(dataguide.js 머리말의 이름 규칙) — 「변수.칸.칸」 을 모은다
JS_READ = re.compile(r"(?<![\w.])(r|res|st|g|grp|it|s|src|run|lastRun|gx|fbox|fnote|task|pit|ear|mk|cg|cc)((?:\??\.[A-Za-z_]\w*)+)")


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
    cgs = [cg for it in g["items"] if it["columns"] for cg in it["columns"]["tables"]]
    objs = {"r": [admin], "res": [admin], "st": [st], "g": [g], "grp": g["groups"], "it": g["items"],
            "s": list(st["items"].values()), "src": g["sources"], "run": [st["runner"]], "lastRun": [st["runner"]["last"]],
            "gx": st["runner"]["groups"], "fbox": g["flow"], "fnote": g["flow_notes"], "task": g["tasks"], "pit": g["pitfalls"],
            "ear": st["early"], "mk": [m for s in st["items"].values() for m in (s["markets"] or [])],
            "cg": cgs, "cc": [cc for cg in cgs for cc in cg["cols"]]}
    src = (PUB / "js" / "dataguide.js").read_text(encoding="utf-8")
    reads = {(m.group(1), tuple(re.findall(r"[A-Za-z_]\w*", m.group(2)))) for m in JS_READ.finditer(src)}
    assert len(reads) > 60, "화면이 읽는 칸을 거의 못 모았다 — 변수 이름 규칙(dataguide.js 머리말)을 볼 것"
    assert {v for v, _ in reads} >= {"cg", "cc"}, "칸 정의(2단계)를 화면이 그린다 — cg · cc 로 읽는 곳이 있어야 한다"
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


# ── 5 · 6. 숫자가 없으면 설명만 · 요청 때 세지 않는다 ───────────────────────────────
def test_no_numbers_gives_descriptions_only(env):
    """TC-DG-05 · 숫자가 없으면 설명만 — 숫자 파일의 표가 모두 「없음」(수집 DB 가 없는 PC) · 매니페스트 없음이면 설명 · 흐름 ·
    길잡이는 다 오고 숫자 칸은 None(말없이 0 을 넣지 않는다) · 까닭이 달린다. 숫자 파일이 아직 없거나(합친 날 · 첫 수집 전) ·
    옛 판이거나 · 깨졌으면 설명은 그대로 · 안내 줄 · 관리자에게는 까닭. 표가 없어도 백업 목록이 있으면 연도별은 오고 줄 수
    칸은 「일부」 로 까닭을 단다."""
    _write(env.numbers, _numbers(missing=True))
    hf = env.cdir.parent / "hf_export" / "meta" / "manifest.json"
    ohlcv = env.cdir / "ohlcv_export" / "manifest.json"
    hf.unlink()
    ohlcv.unlink()
    out = dg.read(admin=False)
    g, st = out["guide"], out["stats"]
    assert len(g["items"]) == len(dg.load_guide()["items"]) and all(it["name"] and it["line"] for it in g["items"])
    assert g["tasks"] and g["pitfalls"] and g["flow"] and g["sources"]
    assert st["available"] is False and st["note"] == "이 PC 에는 모은 자료가 없습니다 — 설명 · 흐름 · 길잡이는 그대로 봅니다"
    assert st["total_rows"] is None and st["first"] is None and st["years"] == []
    for key, s in st["items"].items():
        assert s["rows"] is None and s["last"] is None and not s["years"], key
        assert s["state"] in ("none", "no_link") and s["why"], key
    # 숫자 파일이 아직 없다(합친 날 · 첫 수집 전) — 설명은 그대로 · 「다음 수집 뒤에 보입니다」 · 숫자 칸은 「기다림」
    _write(hf, _hf_manifest())
    _write(ohlcv, _ohlcv_manifest())
    env.numbers.unlink()
    out = dg.read(admin=True)
    st = out["stats"]
    assert st["note"] == "숫자는 매일 낮 수집이 끝날 때 셉니다 — 다음 수집 뒤에 보입니다" and st["measured_at"] is None
    assert st["numbers"] == {"state": "none", "written_at": None}
    s = st["items"]["stock-day"]
    assert s["rows"] is None and s["state"] == "pending" and s["why"] == dg.ITEM_WHY["pending"]
    assert s["years"] == {"2020": 300, "2021": 300}, "백업 목록 숫자는 숫자 파일과 따로 온다"
    assert len(out["guide"]["items"]) == len(g["items"])
    # 옛 판 — 앱이 아는 판과 다르면 숫자를 비우고 안내(관리자에게는 판 번호)
    _write(env.numbers, _numbers(schema=0))
    st = dg.read(admin=True)["stats"]
    assert st["note"] == "숫자 파일이 이 화면보다 옛 판이라 숫자를 비워 둡니다 — 다음 수집 때 새로 씁니다"
    assert st["items"]["stock-day"]["rows"] is None and st["items"]["stock-day"]["state"] == "pending"
    assert st["numbers"]["state"] == "old" and any("판(0)" in x for x in st["dev"]["problems"])
    # 깨진 파일 — 말없이 0 을 넣지 않는다 · 「읽지 못했습니다」
    env.numbers.write_text("{ 깨짐", encoding="utf-8")
    st = dg.read(admin=True)["stats"]
    assert st["problems"] == ["숫자 파일을 읽지 못했습니다"] and st["numbers"]["state"] == "error"
    assert st["note"] == "숫자 파일을 읽지 못했습니다 — 숫자 칸은 비워 두고 설명은 그대로 보입니다"
    assert st["items"]["stock-day"]["state"] == "error" and st["items"]["stock-day"]["rows"] is None
    # 표는 없고 백업 목록만 있는 PC — 연도별은 오고 줄 수는 「일부」 · 까닭
    _write(env.numbers, _numbers(missing=True))
    s = dg.read(admin=False)["stats"]["items"]["stock-day"]
    assert s["rows"] is None and s["years"] == {"2020": 300, "2021": 300} and s["state"] == "partial" and s["why"]


def test_numbers_come_from_the_runner_file_not_from_counting(env):
    """TC-DG-06 · 요청 때 세지 않는다(결정 ④ · 2026-10-11 2단계) — 상태 계산 · 줄 수 세기 · 수집 DB 열기를 부르면 실패하게 막아도
    (픽스처) 숫자는 러너가 쓴 파일에서 온다 · 숫자 기준 시각 = 파일을 쓴 때 · 「모은 줄」 = 파일 표 줄의 합. 수집이 도는 중이면
    「지난 수집(시각) 기준」, 마지막 수집(한 단계 다시 포함) 뒤에 파일을 못 썼으면 「수집 기준 · 새로 쓰지 못했습니다」."""
    _write(env.numbers, _numbers(rows=1234))
    st = dg.read(admin=False)["stats"]
    assert st["measured_at"] == WRITTEN and st["note"] == "" and st["numbers"] == {"state": "ok", "written_at": WRITTEN}
    s = st["items"]["stock-day"]
    assert s["rows"] == 1234 and s["rows_from"] == "numbers" and s["last"] == "2021-10-07" and s["state"] == "ok"
    assert st["total_rows"] == 1234 * len(ds.TABLES) and st["total_state"] == "fresh" and st["as_of"] == "2021-10-07"
    assert "status_pending" not in st
    # 수집이 도는 중 — 숫자는 지난 수집 기준(파일을 쓴 시각)
    _write(env.state / "daily_update.lock", {"pid": 1, "started_at": datetime.now(ds.KST).isoformat(timespec="seconds")})
    st = dg.read(admin=False)["stats"]
    assert st["runner"]["running"] is True
    assert st["note"] == "매일 낮 수집이 도는 중입니다 — 숫자는 지난 수집(10-08 13:25) 기준입니다"
    assert st["items"]["stock-day"]["rows"] == 1234, "도는 동안에도 지난 수집 숫자를 그대로 보인다"
    (env.state / "daily_update.lock").unlink()
    # 마지막 수집(한 단계 다시) 뒤에 파일을 못 썼다 — 숫자는 그대로 · 그 시각 기준이라고 알린다(관리자에게는 까닭)
    _write(env.state / "daily_update_last.json",
           {**LAST, "reruns": [{"name": "news", "at": "2026-10-08T15:00:00+09:00", "rc": 0}]})
    st = dg.read(admin=True)["stats"]
    assert st["note"] == "숫자는 10-08 13:25 수집 기준입니다 — 마지막 수집 뒤에 숫자를 새로 쓰지 못했습니다"
    assert st["numbers"]["state"] == "stale" and st["total_state"] == "stale" and st["items"]["stock-day"]["rows"] == 1234
    assert any(dg.NUMBERS_FILE in x for x in st["dev"]["problems"])


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
    # 칸 대장 — 코드에 없는 칸 · 정한 말 밖의 단위 · 쉬운 칸의 표 이름 · 그 표의 칸 이름 · 안내가 쓰지 않는 표
    c = d / "자료안내-칸.tsv"
    ctext = c.read_text(encoding="utf-8")
    ctext = ctext.replace("price_daily\tclpr\t종가\t원\t", "price_daily\tclpr\t종가\t원화\t", 1)
    ctext = ctext.replace("price_daily\tmkp\t시가\t원\t그날 첫 체결 가격", "price_daily\tmkp\t시가\t원\tclpr 와 같은 날 첫 체결 가격", 1)
    ctext = ctext.replace("price_daily\thipr\t고가\t원\t그날 가장 높은 체결 가격", "price_daily\thipr\t고가\t원\tprice_daily 의 가장 높은 가격", 1)
    ctext += "price_daily\tghost_col\t유령\t원\t코드에 없는 칸\r\nusers\temail\t메일\t글\t안내가 쓰지 않는 표\r\n"
    c.write_text(ctext, encoding="utf-8")
    problems = "\n".join(scan.build(d)[1])
    assert "price_daily.clpr.단위 「원화」 — 정한 단위" in problems
    assert "price_daily.mkp.뜻 — 그 표의 칸 이름 clpr" in problems
    assert "price_daily.hipr.뜻 — 쉬운 칸에 표 이름 price_daily" in problems
    assert "price_daily.ghost_col — 코드에 그런 칸이 없다" in problems
    assert "users — 안내의 자료가 쓰지 않는 표" in problems
    (d / "자료안내-뺀표.tsv").write_text("표\t이유\r\n", encoding="utf-8")
    assert any("자료안내-뺀표.tsv 머리 줄" in x for x in scan.build(d)[1])
    # 점검에 걸리면 쓰지 않는다
    monkeypatch.setattr(scan, "build", lambda *a, **k: ({}, ["시험용 까닭"]))
    out = tmp_path / "새-생성물.json"
    assert scan.main(["--write", "--out", str(out)]) == 1 and not out.exists()
    assert "시험용 까닭" in capsys.readouterr().out

# ── 10. 칸 정의 = 코드의 칸 ──────────────────────────────────────────────────
def test_column_definitions_cover_every_code_column():
    """TC-DG-10 · 칸 정의 = 코드의 칸(2단계 · 사용자 2026-10-11 「35표 · 376칸 모두」) — 안내가 잇는 표의 모든 칸에 쉬운 이름 ·
    단위 · 뜻이 하나씩(빠짐 0 · 남음 0) · 칸 차례 · 타입 · 열쇠는 코드 CREATE 문(앱 표는 모델) 그대로 · 단위는 정한 말 ·
    표가 없는 자료는 칸 정의가 없다(None) · 설명 채움 = 칸 수. 칸을 더하면 칸 대장 줄도 함께 더해야 이 시험이 지나간다."""
    guide = dg.load_guide()
    used = [t for it in guide["items"] for t in it["dev"]["tables"]]
    code = scan.code_columns(set(used))
    assert set(code) == set(used), "안내가 잇는 표를 코드에서 모두 찾는다"
    assert scan.column_coverage(code, scan.read_tsv(scan.LEDGER_DIR / scan.LEDGERS["칸"][0], scan.COL_COLS, [])) == {
        "빠진_칸": [], "남는_칸": []}
    seen: dict[str, int] = {}
    for it in guide["items"]:
        want = it["dev"]["tables"]
        if not want:
            assert it["columns"] is None, it["key"]
            continue
        cols = it["columns"]
        assert [cg["dev"]["table"] for cg in cols["tables"]] == want, it["key"]
        assert cols["count"] == cols["filled"] == sum(len(cg["cols"]) for cg in cols["tables"]) > 0, it["key"]
        for cg in cols["tables"]:
            t = cg["dev"]["table"]
            assert cg["title"] and cg["count"] == len(cg["cols"]), t
            assert [cc["dev"]["col"] for cc in cg["cols"]] == [x["col"] for x in code[t]], f"{t} 칸 차례 = 코드"
            assert [cc["dev"]["key"] for cc in cg["cols"]] == [x["key"] for x in code[t]], f"{t} 열쇠 = 코드"
            assert all(cc["name"] and cc["unit"] in scan.UNITS and cc["text"] for cc in cg["cols"]), t
            seen[t] = len(cg["cols"])
    assert len(seen) == len(set(used)) and sum(seen.values()) == sum(len(code[t]) for t in seen) >= 300
    stock = next(it for it in guide["items"] if it["key"] == "stock-day")
    assert {cc["dev"]["col"] for cc in stock["columns"]["tables"][0]["cols"] if cc["dev"]["key"]} == {"bas_dt", "srtn_cd"}


# ── 11. 쓰는 쪽 → 읽는 쪽 한 줄 ───────────────────────────────────────────────
def test_runner_numbers_file_is_what_the_guide_reads(env, tmp_path, monkeypatch):
    """TC-DG-11 · 쓰는 쪽 → 읽는 쪽 한 줄(DF-102 교훈 — 손으로 만든 파일만 쓰는 시험은 읽는 쪽이 칸을 떨어뜨려도 지나간다) —
    러너의 숫자 함수가 실제 SQLite(표 둘)를 관제와 같은 셈법으로 세어 쓴 파일을 자료 안내가 그대로 읽는다. 없는 표는 「없음」."""
    from scripts import daily_update as du
    db = tmp_path / "m.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE price_daily (bas_dt TEXT, srtn_cd TEXT, PRIMARY KEY (bas_dt, srtn_cd))")
    conn.executemany("INSERT INTO price_daily VALUES (?, ?)", [("20211006", "005930"), ("20211007", "005930"), ("20211007", "000660")])
    conn.execute("CREATE TABLE market_event (event_id TEXT PRIMARY KEY, event_date TEXT)")
    conn.execute("INSERT INTO market_event VALUES ('x:2021-10-08', '2021-10-08')")
    conn.commit()
    conn.close()
    at = datetime(2026, 10, 8, 13, 26, tzinfo=du.KST)
    monkeypatch.setattr(ds, "table_states", _REAL_TABLE_STATES)            # 쓰는 쪽(러너)은 진짜로 센다
    nums = du.table_numbers(db_path=db, now=at)
    monkeypatch.setattr(ds, "table_states", _no_counting)                  # 읽는 쪽(앱)은 다시 세면 실패한다
    assert [t["key"] for t in nums["tables"]] == [key for key, *_ in ds.TABLES], "열쇠 · 차례 = 관제의 표 정의(한 곳)"
    du._write_json_atomic(env.numbers, nums)
    out = dg.read(admin=True)
    st = out["stats"]
    assert st["numbers"]["state"] == "ok" and st["measured_at"] == nums["written_at"] == "2026-10-08T13:26:00+09:00"
    s = st["items"]["stock-day"]
    assert s["rows"] == 3 and s["last"] == "2021-10-07" and s["rows_from"] == "numbers"
    assert st["items"]["events"]["rows"] == 1 and st["items"]["events"]["last"] == "2021-10-08"
    assert st["items"]["etf-day"]["rows"] is None, "없는 표의 숫자는 0 이 아니라 「없음」"
    assert st["total_rows"] == 4 and st["total_partial"] is True
