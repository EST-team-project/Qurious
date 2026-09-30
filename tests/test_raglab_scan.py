"""통합본 반입 폴더 스캐너 시험 (TC-RL) — 「전부 확인했다」 를 검사로 남긴다.

무엇을 지키는가 —
`rag-lab/` 은 다른 저장소를 통째로 옮겨 놓은 폴더라, 그대로 두면 세 가지가 조용히 틀어진다.

1. 누가 파일을 더하거나 고쳐도 아무도 모른다 → 반입 대장(파일마다 git blob ID)과 폴더가 같은지 본다.
2. 빼기로 한 것이 슬그머니 커밋된다 → AWS 설정은 폴더에 없는지, 비공개 데이터셋에 둔 시세 자료는
   .gitignore 에 있는지 본다.
3. 통합본의 화면 · API 중 「어떻게 할지 정하지 않은 것」 이 남는다 → 이식 대장의 묶음 하나에만 들어 있는지 본다.

실제 폴더에는 **늘 참이어야 하는 성질만** 건다(대장과 같다 · 뺀 파일이 없다 · 빠진 화면 · API 가 없다 ·
비밀값 모양이 없다). 「API 가 110개」 같은 지금의 숫자는 걸지 않는다 — 기능을 옮기며 폴더가 줄어드는 것은
좋은 일인데 시험이 깨진다. 판정 규칙은 합성 폴더(tmp_path)로 잰다.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from scripts import raglab_scan as rs

ROOT = Path(__file__).resolve().parents[1]


# ── 실제 폴더 ────────────────────────────────────────────────────────

def test_folder_matches_import_ledger():
    """TC-RL-01 · 폴더가 반입 대장과 같다 — 없어진 파일 · 고친 파일 · 대장에 없는 파일이 0."""
    ledger = rs.read_tsv(rs.IMPORT_LEDGER, rs.IMPORT_COLUMNS)
    assert rs.check_import(ledger) == []


def test_excluded_files_stay_out_of_git():
    """TC-RL-02 · AWS 로 뺀 파일은 폴더에 없고, 비공개 데이터셋에 둔 시세 자료는 .gitignore 에 있다. 둘 다 까닭이 적혀 있다."""
    ledger = rs.read_tsv(rs.IMPORT_LEDGER, rs.IMPORT_COLUMNS)
    out = [r for r in ledger if r["상태"] != rs.STATE_COPIED]
    assert out, "대장에 뺀 파일이 한 줄도 없다 — 대장을 잘못 읽었다"
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for row in out:
        assert row["사유"].strip(), f"{row['경로']}: 뺀 까닭이 비어 있다"
        if row["상태"] == rs.STATE_AWS:
            assert not (rs.FOLDER / row["경로"]).exists(), row["경로"]
        else:                                   # 받아 둔 PC 에서는 폴더에 있을 수 있다 — 커밋만 안 되면 된다
            assert f"rag-lab/{row['경로']}" in ignored, row["경로"]


def test_every_view_and_api_belongs_to_exactly_one_bundle():
    """TC-RL-03 · 통합본의 화면 · API 가 이식 대장의 묶음 하나에만 들어 있다(빠진 것 · 겹친 것 0)."""
    bundles = rs.read_tsv(rs.PORT_LEDGER, rs.PORT_COLUMNS)
    assert rs.check_port(bundles, rs.scan_routes(), rs.scan_views()) == []


def test_every_route_decorator_is_extracted():
    """TC-RL-04 · 라우트 파일의 `@router.메서드(` 수 = 스캐너가 뽑은 API 수 (하나도 놓치지 않는다)."""
    decorators = 0
    for py in sorted((rs.FOLDER / "app" / "api" / "routes").glob("*.py")):
        decorators += len(re.findall(r"^@router\.(?:get|post|put|patch|delete)\(", py.read_text(encoding="utf-8"), re.M))
    assert decorators > 0
    assert len(rs.scan_routes()) == decorators


_SECRET_SHAPES = {
    "AWS 액세스 키": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "개인키": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "토큰": re.compile(rb"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|hf_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,})"),
    "AWS 리소스 이름(계정 번호 포함)": re.compile(rb"arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}"),
}
_BINARY = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".xlsx", ".ico"}


def test_no_secret_shapes_in_folder():
    """TC-RL-05 · 폴더의 글 파일에 비밀값 모양이 없다 — 이 저장소는 공개라, 다음에 들여올 때도 막는다."""
    found = []
    for p in sorted(rs.FOLDER.rglob("*")):
        if not p.is_file() or p.suffix.lower() in _BINARY:
            continue
        data = p.read_bytes()
        for name, shape in _SECRET_SHAPES.items():
            if shape.search(data):
                found.append(f"{p.relative_to(rs.FOLDER).as_posix()}: {name}")
    assert found == []


def test_folder_is_kept_out_of_image_and_requirement_traces():
    """TC-RL-06 · 반입 폴더가 도커 빌드와 요구 추적의 「코드 흔적」 에 끼지 않는다.

    옮겨만 놓은 코드가 흔적으로 잡히면, 아직 만들지 않은 요구가 구현된 것처럼 보인다.
    """
    from scripts import rtm_scan

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "rag-lab" in [line.strip() for line in dockerignore]
    inside = [p for p in rtm_scan.훑을_파일들() if "rag-lab" in p.relative_to(ROOT).parts]
    assert inside == []


# ── 판정 규칙 (합성 폴더) ────────────────────────────────────────────

def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _row(path: str, data: bytes, state: str = "복사", why: str = "") -> dict[str, str]:
    return {"경로": path, "크기": str(len(data)), "blob": _blob(data), "영역": "설정", "종류": "글",
            "원천": "통합본 고유", "상태": state, "사유": why}


@pytest.fixture
def fake_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "FOLDER", tmp_path)
    return tmp_path


def test_blob_id_ignores_line_endings_for_text_only():
    """TC-RL-07 · 글 파일은 줄끝(CRLF · LF)이 달라도 같은 파일로 보고, 그림 같은 이진 파일은 바이트 그대로 본다."""
    lf, crlf = b"a\nb\n", b"a\r\nb\r\n"
    assert _blob(lf) in rs.git_blob_ids(crlf)          # Windows 작업 트리의 CRLF 도 저장될 때의 LF 값과 맞는다
    assert _blob(lf) in rs.git_blob_ids(lf)
    binary = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR"
    assert rs.git_blob_ids(binary) == {_blob(binary)}  # NUL 이 있으면 줄끝을 건드리지 않는다


def test_check_import_passes_when_folder_equals_ledger(fake_folder):
    """TC-RL-08 · (보존 확인) 대장과 폴더가 같으면 어긋난 곳이 없다 — 안내 파일은 대장에 없어도 된다."""
    (fake_folder / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    (fake_folder / rs.GUIDE_FILE).write_text("안내", encoding="utf-8")
    assert rs.check_import([_row("a.txt", b"one\ntwo\n")]) == []


def test_check_import_reports_modified_missing_extra_and_excluded(fake_folder):
    """TC-RL-09 · 고친 파일 · 없어진 파일 · 대장에 없는 파일 · 뺀 파일이 들어온 것을 각각 알린다."""
    (fake_folder / "changed.txt").write_bytes(b"after\n")
    (fake_folder / "extra.txt").write_bytes(b"x\n")
    (fake_folder / "deploy.yml").write_bytes(b"aws\n")
    problems = rs.check_import([
        _row("changed.txt", b"before\n"),
        _row("missing.txt", b"gone\n"),
        _row("deploy.yml", b"aws\n", state="AWS 제외", why="배포 워크플로"),
    ])
    text = "\n".join(problems)
    assert "changed.txt: 내용이 대장의 blob 과 다르다" in text
    assert "missing.txt: 대장에는 복사로 적혔는데 폴더에 없다" in text
    assert "extra.txt: 폴더에 있는데 대장에 없다" in text
    assert "deploy.yml: 「AWS 제외」 로 뺀 파일이 폴더에 들어와 있다" in text
    assert len(problems) == 4


def test_held_data_must_be_gitignored_and_match_when_present(fake_folder, monkeypatch, tmp_path_factory):
    """TC-RL-14 · 비공개 데이터셋에 둔 파일은 폴더에 없어도 되지만, .gitignore 에 없거나 받아 둔 내용이 다르면 알린다."""
    gitignore = tmp_path_factory.mktemp("repo") / ".gitignore"
    monkeypatch.setattr(rs, "GITIGNORE", gitignore)
    row = _row("data/etf.json", b'{"a": 1}\n', state="HF 보관", why="시세 자료")
    ignore_line = f"{fake_folder.name}/data/etf.json\n"

    gitignore.write_text(ignore_line, encoding="utf-8")
    assert rs.check_import([row]) == []                         # 안 받아 둔 PC — 어긋난 곳 없음
    (fake_folder / "data").mkdir()
    (fake_folder / "data" / "etf.json").write_bytes(b'{"a": 1}\r\n')
    assert rs.check_import([row]) == []                         # 받아 둔 PC — 내용이 같으면 통과

    gitignore.write_text("", encoding="utf-8")
    assert ".gitignore 에" in "\n".join(rs.check_import([row]))   # 커밋될 수 있는 상태
    gitignore.write_text(ignore_line, encoding="utf-8")
    (fake_folder / "data" / "etf.json").write_bytes(b'{"a": 2}\n')
    assert "받아 둔 파일이 대장의 blob 과 다르다" in "\n".join(rs.check_import([row]))


def test_check_port_reports_orphans_overlaps_and_stale_names():
    """TC-RL-10 · 묶음에 없는 화면 · 두 묶음에 걸친 API · 통합본에 없는 이름을 각각 알린다."""
    views = [{"set": "분석", "view": "learn-03"}, {"set": "분석", "view": "orphan"}]
    routes = [{"method": "GET", "path": "/api/quiz/day/{day}"}, {"method": "GET", "path": "/api/search"}]
    base = {"요구ID": "—", "Qurious에_있는_것": "—", "판정": "합침", "차례": "1", "상태": "안 함", "비고": ""}
    bundles = [
        {"묶음ID": "R01", "묶음": "학습", "화면": "분석:learn-*", "API": "/api/search · /api/quiz/*", **base},
        {"묶음ID": "R02", "묶음": "퀴즈", "화면": "분석:gone", "API": "/api/quiz/*", **base},
    ]
    text = "\n".join(rs.check_port(bundles, routes, views))
    assert "화면 분석:orphan: 묶음 0곳" in text
    assert "API GET /api/quiz/day/{day}: 묶음 2곳" in text
    assert "이식 대장 R02: 화면 「분석:gone」 가 통합본에 없다" in text
    assert "learn-03" not in text and "/api/search:" not in text      # 제대로 든 것은 말하지 않는다


def test_check_port_rejects_unknown_verdict_and_progress():
    """TC-RL-11 · 판정 · 상태 칸은 정한 말만 쓴다(새 화면 · 합침 · 바꿈 · 참고 · 보류 · 제외 / 안 함 · 설계 · 구현 · 끝)."""
    bundle = {"묶음ID": "R01", "묶음": "x", "화면": "—", "API": "—", "요구ID": "—", "Qurious에_있는_것": "—",
              "판정": "나중에", "차례": "—", "상태": "거의", "비고": ""}
    text = "\n".join(rs.check_port([bundle], [], []))
    assert "판정 「나중에」" in text and "상태 「거의」" in text


def test_route_scan_follows_prefix_helpers_and_registration(fake_folder):
    """TC-RL-12 · 라우터 prefix 를 붙이고, 같은 파일의 도움 함수까지 따라가 닿는 곳을 찾고, 앱에 안 걸린 파일을 가린다."""
    routes = fake_folder / "app" / "api" / "routes"
    routes.mkdir(parents=True)
    (routes / "market.py").write_text(
        'from fastapi import APIRouter\n'
        'router = APIRouter(prefix="/market")\n\n'
        'def _load(ticker):\n    import yfinance as yf\n    return yf.download(ticker)\n\n'
        '@router.get("/history")\ndef price_history(ticker: str):\n    """과거 시세."""\n    return _load(ticker)\n',
        encoding="utf-8")
    (routes / "dead.py").write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n\n'
        '@router.post("/api/rag/ask")\ndef ask():\n    return {}\n', encoding="utf-8")
    (fake_folder / "app" / "main.py").write_text(
        'from app.api.routes.market import router as market_router\n'
        'from app.api.routes.dead import router as dead_router\n'
        'app.include_router(market_router)\n', encoding="utf-8")
    front = fake_folder / "frontend"
    front.mkdir()
    (front / "app.js").write_text("fetch(`/market/history?ticker=${t}`)", encoding="utf-8")

    by_path = {r["path"]: r for r in rs.scan_routes()}
    history = by_path["/market/history"]
    assert history["method"] == "GET" and history["summary"] == "과거 시세."
    assert "야후" in history["touches"]                   # 본문이 아니라 도움 함수 안의 yfinance 를 따라가 찾는다
    assert history["callers"] == ["frontend/app.js"]      # 물음표 뒤(쿼리)는 떼고 맞춘다
    assert history["registered"] is True
    assert by_path["/api/rag/ask"]["registered"] is False  # import 만 하고 include_router 로 걸지 않았다
    assert by_path["/api/rag/ask"]["callers"] == []


def test_fill_document_replaces_only_marked_blocks():
    """TC-RL-13 · 문서의 표시된 블록만 다시 채우고, 모르는 블록 이름이면 멈춘다."""
    doc = "머리\n<!-- raglab_scan:stores -->\n옛 표\n<!-- /raglab_scan:stores -->\n꼬리\n"
    out = rs.fill_document(doc, {"stores": "새 표"})
    assert out == "머리\n<!-- raglab_scan:stores -->\n새 표\n<!-- /raglab_scan:stores -->\n꼬리\n"
    assert rs.fill_document(out, {"stores": "새 표"}) == out          # 다시 돌려도 같다
    empty = "<!-- raglab_scan:stores -->\n<!-- /raglab_scan:stores -->\n"  # 처음 쓰는 문서 — 사이가 비어 있다
    assert rs.fill_document(empty, {"stores": "가\n나"}) == "<!-- raglab_scan:stores -->\n가\n나\n<!-- /raglab_scan:stores -->\n"
    crlf = "<!-- raglab_scan:stores -->\r\n옛\r\n<!-- /raglab_scan:stores -->\r\n"   # Windows 작업 트리의 줄끝을 따른다
    assert rs.fill_document(crlf, {"stores": "가\n나"}) == "<!-- raglab_scan:stores -->\r\n가\r\n나\r\n<!-- /raglab_scan:stores -->\r\n"
    with pytest.raises(SystemExit):
        rs.fill_document(doc.replace("stores", "nope"), {"stores": "새 표"})
