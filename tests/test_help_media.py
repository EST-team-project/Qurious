"""TC-HM — 사용법 영상의 원천(결정 D132 · 2026-10-18)

화면(TC-HT · public/js/howto.js · howtoview.js)이 읽는 영상 표와 파일이 어디서 어떻게 오는지를 지킨다.
1. 라우트 둘(app/routes/help_media.py) — 영상 표 /help/videos.json(API-HELP-01) · 파일 /help/media/{이름}(API-HELP-02) ·
   로그인한 사람에게만(401) · 영상을 받지 않은 PC 는 영상 표가 빈 표(200 · StaticFiles 처럼 500 이 아니라) · 그 밖은 404 ·
   파일은 영상 · 자막 · 장 그림 꼴만 · 폴더 밖 · 숨은 이름은 404 · Range 206 · 영상 표는 no-cache. (TC-HM-01 ~ 03)
2. 받기 도구(tools/demo/help_videos.py) — 녹화 기록의 단계 시각 · go 화면 키와 장 파일로 표를 만든다(손으로 쓰지 않음):
   시작 화면은 장 1 · go 화면은 그 시각이 든 장 · 처음 나온 곳만 · 한 화면이 여러 영상에 나오면 그 화면에서 시작하는 영상 →
   여정(V) → 기능(F) · 화면 키 없는 옛 기록은 장면 파일과 같은 앞쪽까지만 · 멈춘 녹화 · 영상 없는 녹화는 빼고 까닭을 남김 ·
   화면에 나갈 제목에 편 번호 · 파일 이름 · 작업 낱말이 있으면 멈추고 폴더를 그대로 · 주소는 퍼센트 부호 + 내용 지문 ·
   표는 파일을 다 옮긴 뒤에 · 표에 없는 옛 파일은 지움 · 같은 파일은 다시 옮기지 않음. (TC-HM-04 ~ 08)
3. 장면 파일 — 장 · 영상 제목에 쓰지 않는 말이 없고 · start · go 화면 키가 앱에 있는 화면이다. (TC-HM-09)
4. 연결 — main.py 가 라우터를 싣고 · .gitignore · .dockerignore 가 data/help 를 빼고 · compose 가 ./data 를 앱에 이미 붙인다. (TC-HM-10)
손 몫(실제 앱에서 재생 · 장부터 · Range · 404 숨김)은 tests/e2e/howto_video.py.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import help_media

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "docs" / "영상" / "장면"


def _tool():
    spec = importlib.util.spec_from_file_location("help_videos_under_test", ROOT / "tools" / "demo" / "help_videos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hv = _tool()


# ── 1. 라우트 ─────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch, *, login=True, folder=True):
    base = tmp_path / "help"
    if folder:
        (base / "media").mkdir(parents=True)
    monkeypatch.setenv(help_media.ENV_DIR, str(base))
    app = FastAPI()
    app.include_router(help_media.router)
    if login:
        app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}
    return TestClient(app), base


def test_route_login_and_missing_folder(tmp_path, monkeypatch):
    """TC-HM-01 · 로그인한 사람에게만(401) · 영상을 받지 않은 PC(폴더 없음) — 영상 표는 빈 표(200 · 콘솔 오류 없음) · 그 밖은 404 · 500 이 아니다"""
    c, _ = _client(tmp_path, monkeypatch, login=False)
    assert c.get("/help/videos.json").status_code == 401, "HF 비공개 자료라 로그인 뒤에만(개념 학습 팀 자료와 같은 꼴)"
    assert c.get("/help/media/a.webm").status_code == 401, "파일도 로그인 뒤에만"
    c, base = _client(tmp_path / "x", monkeypatch, folder=False)
    assert not base.exists()
    r = c.get("/help/videos.json")
    assert r.status_code == 200 and r.json() == {"format": 1, "videos": {}, "views": {}, "missing": True}, "빈 표 — 화면은 영상 칸을 숨긴다(결정 ⑥)"
    assert r.headers["cache-control"] == "no-cache", "영상을 받은 뒤 새로 고치면 바로 보이게"
    assert c.get("/help/media/a.webm").status_code == 404 and c.get("/help/x.json").status_code == 404, "영상 표 밖은 404"
    (base / "media").mkdir(parents=True)
    assert c.get("/help/videos.json").json()["missing"] is True, "폴더만 있고 표가 없어도(옮기는 중) 빈 표"


def test_route_serves_only_known_kinds_inside(tmp_path, monkeypatch):
    """TC-HM-02 · 내는 꼴만 · 폴더 밖 · 숨은 이름은 404 · 영상 표 no-cache · 그 밖은 private 하루"""
    c, base = _client(tmp_path, monkeypatch)
    (base / "videos.json").write_text('{"format": 1}', encoding="utf-8")
    (base / "media" / "a.webm").write_bytes(bytes(range(256)) * 4)
    (base / "media" / "a.ko.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (base / "media" / "a.ch1.jpg").write_bytes(b"\xff\xd8\xff")
    (base / "media" / "note.txt").write_text("x", encoding="utf-8")
    (base / "media" / "copy.json").write_text("{}", encoding="utf-8")
    (base / "media" / ".hidden.webm").write_bytes(b"x")
    (base / ".secret.json").write_text("{}", encoding="utf-8")
    (tmp_path / "outside.json").write_text("{}", encoding="utf-8")
    r = c.get("/help/videos.json")
    assert r.status_code == 200 and r.json() == {"format": 1} and r.headers["cache-control"] == "no-cache"
    r = c.get("/help/media/a.webm")
    assert r.status_code == 200 and r.headers["content-type"] == "video/webm" and r.headers["cache-control"] == "private, max-age=86400"
    assert c.get("/help/media/a.ko.vtt").headers["content-type"].startswith("text/vtt")
    assert c.get("/help/media/a.ch1.jpg").headers["content-type"] == "image/jpeg"
    for bad in ("/help/media/note.txt", "/help/media/copy.json", "/help/media/.hidden.webm", "/help/.secret.json",
                "/help/media/none.webm", "/help/media", "/help/media/x/a.webm", "/help/media/..%2F..%2Foutside.json"):
        assert c.get(bad).status_code == 404, bad
    for rel in ("../outside.json", "media/../../outside.json", "media/./a.webm", ".secret.json", "media\\..\\..\\outside.json", ""):
        assert help_media.resolve(rel) is None, f"폴더 밖 · 숨은 이름 · 빈 경로는 내지 않는다 — {rel!r}"
    assert help_media.resolve("media/a.webm") == (base / "media" / "a.webm").resolve()


def test_route_range_for_seeking(tmp_path, monkeypatch):
    """TC-HM-03 · 장 단추 · 건너뛰기 — Range 요청에 206 · 그 범위만"""
    c, base = _client(tmp_path, monkeypatch)
    (base / "media" / "a.webm").write_bytes(bytes(range(256)) * 4)
    r = c.get("/help/media/a.webm", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == bytes(range(100, 200)) and r.headers["content-range"] == "bytes 100-199/1024"


def test_help_dir_follows_collector_path(tmp_path, monkeypatch):
    """TC-HM-01 덧 · 폴더 자리 — 환경 변수 → 도커(./data 가 /app/data/csv 에 붙음) → 로컬 data/help (수집 DB 와 같은 길)"""
    monkeypatch.delenv(help_media.ENV_DIR, raising=False)
    monkeypatch.setattr(help_media, "_ROOT", tmp_path)
    assert help_media.help_dir() == tmp_path / "data" / "help", "로컬"
    (tmp_path / "data" / "csv").mkdir(parents=True)
    assert help_media.help_dir() == tmp_path / "data" / "csv" / "help", "도커 — compose 를 고치지 않고 보인다"
    monkeypatch.setenv(help_media.ENV_DIR, str(tmp_path / "e"))
    assert help_media.help_dir() == tmp_path / "e"


# ── 2. 받기 도구 ───────────────────────────────────────────────────────────────

def _vtt(cues):
    out = ["WEBVTT", ""]
    for a, b, t in cues:
        out.append(f"{_t(a)} --> {_t(b)}\n{t}\n")
    return "\n".join(out)


def _t(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


CH3 = [(0.0, 15.48, "신호로 후보 종목을 거릅니다"), (15.48, 30.6, "한 종목의 차트를 읽습니다"), (30.6, 38.36, "신호는 판단의 재료입니다")]


def _rec(src, name, *, start, gos=(), chapters=CH3, ok=True, webm=True, posters=True, views_in_log=True, title="영상 제목", duration=38.64):
    """녹화기(tools/demo/record_demo.py)가 남기는 꼴 그대로 — 기록 · 영상 · 자막 · 장 · 장 그림."""
    src.mkdir(parents=True, exist_ok=True)
    steps = [{"i": 1, "step": "chapter", "t": 0.0, "dur": 3.5}]
    for i, (view, t) in enumerate(gos, 2):
        s = {"i": i, "step": "go", "t": t, "dur": 1.5}
        if views_in_log:
            s["view"] = view
        steps.append(s)
    meta = {"file": name, "ok": ok, "duration_sec": duration, "steps": steps, "recorded_at": "2026-10-18 20:00:00 KST", "app_commit": "abc1234"}
    if views_in_log:
        meta.update({"title": title, "start": start})
    (src / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if webm:
        (src / f"{name}.webm").write_bytes(name.encode("utf-8") * 50)
    (src / f"{name}.ko.vtt").write_text(_vtt([(1.0, 3.0, "자막")]), encoding="utf-8")
    (src / f"{name}.chapters.vtt").write_text(_vtt(chapters), encoding="utf-8")
    if posters:
        for k in range(1, len(chapters) + 1):
            (src / f"{name}.ch{k}.jpg").write_bytes(f"{name}{k}".encode("utf-8"))


def test_views_map_to_the_chapter_where_the_screen_appears(tmp_path):
    """TC-HM-04 · 시작 화면은 장 1 · go 화면은 그 시각이 든 장 · 처음 나온 곳만 · 그 화면에서 시작하는 영상이 먼저 · V → F"""
    src = tmp_path / "out"
    _rec(src, "V03-신호로-종목살피기", start="robo-screening", gos=[("robo-patterns", 18.84), ("robo-screening", 33.0)])
    _rec(src, "F04-한종목", start="agent-news", gos=[("market-calendar", 20.0), ("robo-patterns", 25.0)])
    _rec(src, "F06-시장", start="market-calendar", gos=[("macro-industry", 16.0)])
    man, files, problems = hv.build_manifest(src, source="out", scene_dir=tmp_path / "none")
    v = man["views"]
    assert v["robo-screening"] == {"video": "V03-신호로-종목살피기", "chapter": 0}, "시작 화면 · 뒤에 다시 나와도 처음 나온 장"
    assert v["robo-patterns"] == {"video": "V03-신호로-종목살피기", "chapter": 1}, "차트 패턴 = 장 2(18.84초가 든 장)"
    assert v["market-calendar"] == {"video": "F06-시장", "chapter": 0}, "그 화면에서 시작하는 영상이 다른 영상의 중간보다 먼저"
    assert v["macro-industry"] == {"video": "F06-시장", "chapter": 1} and v["agent-news"]["chapter"] == 0
    assert list(man["videos"]) == ["V03-신호로-종목살피기", "F04-한종목", "F06-시장"], "여정(V) → 기능(F)"
    assert man["format"] == 1 and man["source"] == "out" and problems == []
    row = man["videos"]["V03-신호로-종목살피기"]
    assert [c["start"] for c in row["chapters"]] == [0.0, 15.48, 30.6] and row["duration"] == 38.64
    assert row["src"].startswith("/help/media/V03-%EC%8B%A0") and re.search(r"\.webm\?v=[0-9a-f]{12}$", row["src"]), "주소는 퍼센트 부호 + 내용 지문"
    assert all(c["poster"].startswith("/help/media/") for c in row["chapters"]) and len(files) == 3 * (1 + 2 + 3)


def test_bad_recordings_are_left_out_with_a_reason(tmp_path):
    """TC-HM-05 · 멈춘 녹화 · 영상 없는 녹화 · 장 없는 녹화는 빼고 까닭을 남긴다(말없이 지나가지 않음)"""
    src = tmp_path / "out"
    _rec(src, "V01-좋음", start="robo-portfolio")
    _rec(src, "V02-멈춤", start="agent-products", ok=False)
    _rec(src, "V05-영상없음", start="robo-rebalance", webm=False)
    _rec(src, "V07-장없음", start="agent-chat", chapters=[])
    man, files, problems = hv.build_manifest(src, source="out", scene_dir=tmp_path / "none")
    assert list(man["videos"]) == ["V01-좋음"] and list(man["views"]) == ["robo-portfolio"]
    joined = "\n".join(problems)
    assert "V02-멈춤" in joined and "ok=false" in joined and "V05-영상없음" in joined and "V07-장없음" in joined


def test_old_logs_use_the_scene_file_only_while_it_matches(tmp_path):
    """TC-HM-06 · 화면 키 없는 옛 기록 — 장면 파일과 단계 차례 · 종류가 같은 앞쪽의 go 만 쓰고 그 뒤가 달라지면 알린다"""
    src, scenes = tmp_path / "out", tmp_path / "scenes"
    scenes.mkdir()
    _rec(src, "V03-옛", start="robo-screening", gos=[("robo-patterns", 18.84), ("us-order", 33.0)], views_in_log=False)
    scene = {"file": "V03-옛", "title": "옛 영상", "start": "robo-screening",
             "steps": [{"chapter": {"title": "a"}}, {"go": "robo-patterns"}, {"say": "녹화 뒤에 끼운 줄"}, {"go": "us-order"}]}
    (scenes / "V03-옛.yaml").write_text(yaml.safe_dump(scene, allow_unicode=True), encoding="utf-8")
    man, _, problems = hv.build_manifest(src, source="out", scene_dir=scenes)
    assert man["views"]["robo-patterns"] == {"video": "V03-옛", "chapter": 1}, "어긋나기 전의 go 는 맞다(같은 단계를 가리킴)"
    assert "us-order" not in man["views"], "어긋난 뒤의 go 는 쓰지 않는다"
    assert any("3번째 단계부터" in p for p in problems), problems
    assert man["videos"]["V03-옛"]["title"] == "옛 영상"


def test_forbidden_words_stop_the_build(tmp_path):
    """TC-HM-07 · 화면에 나갈 장 · 영상 제목에 편 번호 · 파일 이름 · 작업 낱말이 있으면 멈추고 폴더를 그대로 둔다"""
    assert hv.bad_words("V03 장면에서 HF 로") == ["장면", "HF", "V03"]
    assert hv.bad_words("한 종목의 차트를 읽습니다") == [] and hv.bad_words("EV03 · F1 · 2V03x") == []
    src, dest = tmp_path / "out", tmp_path / "help"
    _rec(src, "V01-나쁨", start="robo-portfolio", chapters=[(0.0, 5.0, "시연 계정으로 봅니다")])
    _rec(src, "V02-좋음", start="agent-products")
    man, files, problems = hv.build_manifest(src, source="out", scene_dir=tmp_path / "none")
    assert "V01-나쁨" not in man["videos"] and any("쓰지 않는 말" in p for p in problems)
    assert hv.finish(man, files, problems, dest) == 1 and not dest.exists(), "걸리면 폴더를 만들지도 바꾸지도 않는다"


def test_install_writes_the_table_last_and_cleans_up(tmp_path):
    """TC-HM-08 · 옮기기 — 표는 파일을 다 옮긴 뒤에 · 표에 없는 옛 파일은 지움 · 같은 파일은 다시 옮기지 않음 · status 는 빠진 파일을 잡음"""
    src, dest = tmp_path / "out", tmp_path / "help"
    _rec(src, "V01-하나", start="robo-portfolio")
    man, files, problems = hv.build_manifest(src, source="out", scene_dir=tmp_path / "none")
    (dest / "media").mkdir(parents=True)
    (dest / "media" / "V99-옛영상.webm").write_bytes(b"old")
    (dest / "media" / "keep.txt").write_text("손대지 않음", encoding="utf-8")
    copied, removed = hv.install(man, files, dest)
    assert copied == len(files) and removed == 1 and not (dest / "media" / "V99-옛영상.webm").exists()
    assert (dest / "media" / "keep.txt").exists(), "우리 꼴(.webm · .vtt · .jpg) 밖의 파일은 지우지 않는다"
    assert json.loads((dest / "videos.json").read_text(encoding="utf-8"))["views"] == {"robo-portfolio": {"video": "V01-하나", "chapter": 0}}
    assert not (dest / "videos.json.tmp").exists()
    assert hv.install(man, files, dest) == (0, 0), "같은 파일은 다시 옮기지 않는다"
    class A:
        pass
    a = A()
    a.dest = str(dest)
    assert hv.cmd_status(a) == 0
    (dest / "media" / "V01-하나.ch2.jpg").unlink()
    assert hv.cmd_status(a) == 1, "표에 있는데 빠진 파일(장 그림)도 잡는다"


# ── 3 · 4. 장면 파일 · 연결 ─────────────────────────────────────────────────────

def test_scene_files_text_and_views():
    """TC-HM-09 · 장면 파일 — 장 · 영상 제목에 쓰지 않는 말 0 · start · go 화면 키는 앱에 있는 화면"""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    views = set(re.findall(r'class="view[^"]*"[^>]*data-view="([^"]+)"', html)) | set(re.findall(r'data-view="([^"]+)"[^>]*class="view', html))
    assert len(views) >= 70
    files = sorted(SCENES.glob("*.yaml"))
    assert files, "장면 파일이 없다"
    for f in files:
        sc = yaml.safe_load(f.read_text(encoding="utf-8"))
        titles = [sc.get("title", "")] + [s["chapter"].get("title", "") for s in sc["steps"] if "chapter" in s]
        bad = [w for t in titles for w in hv.bad_words(t)]
        assert not bad, f"{f.name} 제목에 {bad}"
        assert sc.get("start") in views, f"{f.name} start {sc.get('start')}"
        for s in sc["steps"]:
            if "go" in s:
                g = s["go"] if isinstance(s["go"], str) else s["go"]["view"]
                assert g in views, f"{f.name} go {g}"


def test_wiring():
    """TC-HM-10 · 연결 — main.py 가 라우터를 싣는다 · data/help 는 git · 이미지 밖 · compose 가 ./data 를 앱에 이미 붙인다"""
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.routes import help_media as help_media_routes" in main and "app.include_router(help_media_routes.router)" in main
    assert re.search(r"^data/help/\s*$", (ROOT / ".gitignore").read_text(encoding="utf-8"), re.M), "영상은 git 에 넣지 않는다"
    assert re.search(r"^data/help\s*$", (ROOT / ".dockerignore").read_text(encoding="utf-8"), re.M), "영상은 이미지에 넣지 않는다"
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    app_block = compose[compose.index("\n  app:"):compose.index("\n  celery-worker:")]
    assert "- ./data:/app/data/csv:ro" in app_block, "앱 컨테이너가 data/help 를 /app/data/csv/help 로 본다(이 줄이 빠지면 영상이 숨는다)"
    assert help_media.MANIFEST == "videos.json" == hv.MANIFEST_NAME and hv.URL_BASE == "/help/media/"
    assert help_media.EMPTY_MANIFEST["format"] == hv.FORMAT, "빈 표도 같은 판(화면이 판을 보고 읽는다)"
    view = (ROOT / "public" / "js" / "howtoview.js").read_text(encoding="utf-8")
    assert 'export const VIDEO_MANIFEST_URL = "/help/videos.json";' in view and f"export const VIDEO_FORMAT = {hv.FORMAT};" in view, "도구와 화면이 같은 표 판"
