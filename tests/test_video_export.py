"""시연 영상 내보내기 시험 (TC-VX) — tools/demo/export_mp4.py · 2026-10-19 사용자 결정 「mp4 + 발표 자료가 재생」 · 같은 날 「mp4 는 git 밖」 → 2026-10-20 「git 에 올림(팀원이 받아 재생)」.

지키는 것
1. 녹화 뒤 장면 파일이 바뀐 영상은 내보내지 않는다 — 새 녹화는 장면 지문, 지문 없는 옛 녹화는 자막 · 장 제목 맞대기.
2. 다시 돌리면 0편(원본 · 결과 지문이 목록과 같으면 건너뜀) · 편마다 10 MB 안(넘으면 CRF 를 올리고, 끝까지 넘으면 멈춤).
3. mp4 · 그림은 git 에 둔다(2026-10-20 사용자 결정 — 팀원이 받아 발표 자료에서 재생) · 이 PC 에 있으면 목록.json 과 맞고, 발표 자료의 영상 칸은 내보내기 폴더를 가리킨다.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ex():
    spec = importlib.util.spec_from_file_location("export_mp4_under_test", ROOT / "tools" / "demo" / "export_mp4.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SCENE = {
    "file": "시험-V99-예시", "title": "예시 영상", "start": "dashboard",
    "steps": [
        {"chapter": {"label": "1 / 2 · 목적", "title": "첫 장", "text": "설명", "sec": 3}},
        {"say": "첫 자막"},
        {"pause": 1.0},
        {"say": ""},
        {"chapter": {"label": "2 / 2 · 결과", "title": "둘째 장", "text": "설명", "sec": 3}},
        {"say": {"text": "둘째 자막"}},
    ],
}


def vtt(*cues):
    body = ["WEBVTT", ""]
    for i, t in enumerate(cues):
        body += [f"00:00:0{i}.000 --> 00:00:0{i}.900", *t.split("\n"), ""]
    return "\n".join(body)


def test_vtt_texts_reads_cue_text_in_order(ex, tmp_path):
    """TC-VX-01 · 자막 파일은 글 줄만 차례대로 — 머리 · 시각 줄 · 빈 줄은 빼고, 두 줄짜리 글은 한 줄로 잇는다."""
    p = tmp_path / "a.vtt"
    p.write_text(vtt("첫 자막", "둘째\n줄바꿈"), encoding="utf-8")
    assert ex.vtt_texts(p) == ["첫 자막", "둘째 줄바꿈"]
    assert ex.vtt_texts(tmp_path / "없음.vtt") == []


def test_recording_must_match_the_current_scene(ex):
    """TC-VX-02 · 지문이 있으면 지문으로, 없으면 자막 · 장 제목으로 「이 장면으로 찍은 녹화인가」 를 가린다 — 빈 자막은 세지 않는다."""
    says, chaps = ["첫 자막", "둘째 자막"], ["첫 장", "둘째 장"]
    assert ex.scene_texts(SCENE) == (says, chaps)
    ok, why = ex.recording_matches(SCENE, "aaaa", {"ok": True}, says, chaps)
    assert ok and "옛 녹화" in why
    ok, why = ex.recording_matches(SCENE, "aaaa", {"ok": True}, ["첫 자막", "고친 자막"], chaps)
    assert not ok and "바뀜" in why
    ok, why = ex.recording_matches(SCENE, "aaaa", {"ok": True}, says, ["첫 장", "고친 장"])
    assert not ok and "장 제목" in why
    assert ex.recording_matches(SCENE, "aaaa", {"ok": True, "scene_sha": "aaaa"}, [], [])[0] is True
    ok, why = ex.recording_matches(SCENE, "aaaa", {"ok": True, "scene_sha": "bbbb"}, says, chaps)
    assert not ok and "지문" in why                           # 지문이 있으면 자막이 같아도 지문이 이긴다
    ok, why = ex.recording_matches(SCENE, "aaaa", {"ok": False, "failed_at": "3번째 단계"}, says, chaps)
    assert not ok and "녹화 실패" in why


def test_scene_sha_folds_line_endings(ex, tmp_path):
    """TC-VX-03 · 장면 지문은 줄 끝을 접어서 — autocrlf 작업 트리(CRLF)와 녹화 때(LF)가 같은 값이어야 한다 · 녹화기도 같은 셈을 쓴다."""
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_bytes(b"file: x\nsteps: []\n")
    b.write_bytes(b"file: x\r\nsteps: []\r\n")
    assert ex.scene_sha(a) == ex.scene_sha(b)
    rec = (ROOT / "tools" / "demo" / "record_demo.py").read_text(encoding="utf-8")
    assert re.search(r'"scene_sha":\s*hashlib\.sha256\(Path\(scene_path\)\.read_bytes\(\)\.replace\(b"\\r\\n", b"\\n"\)\)\.hexdigest\(\)\[:16\]', rec)


@pytest.fixture
def layout(ex, tmp_path, monkeypatch):
    """가짜 저장소 — 장면 폴더 · 녹화 결과 · 내보낼 곳 · 목록을 임시 폴더에 두고 인코더를 갈음한다."""
    scenes, out, dest = tmp_path / "scenes", tmp_path / "out", tmp_path / "dest"
    for d in (scenes, out):
        d.mkdir()
    (scenes / "V99-예시.yaml").write_text(yaml.safe_dump(SCENE, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(ex, "ROOT", tmp_path)
    monkeypatch.setattr(ex, "KINDS", (("사용법", scenes, out, dest / "사용법"),))
    monkeypatch.setattr(ex, "DEST", dest)
    monkeypatch.setattr(ex, "MANIFEST", dest / "목록.json")
    calls = []

    def fake_encode(ff, src, dst, crf):
        calls.append(crf)
        dst.write_bytes(b"mp4" + str(crf).encode() + src.read_bytes()[:16])
        return dst.stat().st_size

    monkeypatch.setattr(ex, "encode", fake_encode)
    return {"scenes": scenes, "out": out, "dest": dest, "calls": calls}


def record(layout, says=("첫 자막", "둘째 자막"), chaps=("첫 장", "둘째 장"), ok=True, content=b"webm-1"):
    o = layout["out"]
    (o / "시험-V99-예시.webm").write_bytes(content)
    (o / "시험-V99-예시.json").write_text(json.dumps({"ok": ok, "duration_sec": 65.0, "recorded_at": "2026-10-19 09:00:00 KST",
                                                   "app_commit": "abc1234"}), encoding="utf-8")
    (o / "시험-V99-예시.ko.vtt").write_text(vtt(*says), encoding="utf-8")
    (o / "시험-V99-예시.chapters.vtt").write_text(vtt(*chaps), encoding="utf-8")
    (o / "시험-V99-예시.ch1.jpg").write_bytes(b"jpg")


def test_export_once_then_nothing_and_stale_scene_is_held(ex, layout):
    """TC-VX-04 · 녹화 없음 → 내보낼 것 → 내보냄(다시 돌리면 0편) · 장면을 고치면 「장면이 바뀜」 으로 막는다 · 새 녹화면 다시 내보낸다."""
    rows = ex.entries()
    assert [ex.status(r, {})[0] for r in rows] == ["녹화 없음"]
    record(layout)
    man = {}
    assert ex.status(rows[0], man)[0] == "내보낼 것"
    ex.export(rows[0], "ffmpeg", man)
    mp4 = layout["dest"] / "사용법" / "V99-예시.mp4"
    assert mp4.exists() and (layout["dest"] / "사용법" / "V99-예시.jpg").exists()
    e = man[("사용법", "V99-예시")]
    assert e["mp4"] == "dest/사용법/V99-예시.mp4" and e["crf"] == 28 and e["source_sha"] == ex.file_sha(layout["out"] / "시험-V99-예시.webm")
    assert ex.status(ex.entries()[0], man)[0] == "내보냄"
    ex.save_manifest(man)
    assert ex.status(ex.entries()[0], ex.load_manifest())[0] == "내보냄"          # 파일에서 다시 읽어도 같다
    y = layout["scenes"] / "V99-예시.yaml"
    y.write_text(y.read_text(encoding="utf-8").replace("둘째 자막", "고친 자막"), encoding="utf-8")
    st, why = ex.status(ex.entries()[0], man)
    assert st == "장면이 바뀜" and "자막" in why
    record(layout, says=("첫 자막", "고친 자막"), content=b"webm-2")            # 고친 장면으로 다시 찍으면
    assert ex.status(ex.entries()[0], man)[0] == "내보낼 것"


def test_size_limit_raises_crf_then_stops(ex, layout, monkeypatch):
    """TC-VX-05 · 10 MB 를 넘으면 CRF 28 → 31 → 34 로 줄이고, 끝까지 넘으면 파일을 지우고 멈춘다(GitHub 첨부 한도)."""
    record(layout)
    row = ex.entries()[0]
    sizes = {28: 12_000_000, 31: 10_500_000, 34: 9_000_000}

    def sized(ff, src, dst, crf):
        layout["calls"].append(crf)
        dst.write_bytes(b"x")
        return sizes[crf]

    monkeypatch.setattr(ex, "encode", sized)
    man = {}
    size, crf = ex.export(row, "ffmpeg", man)
    assert (size, crf) == (9_000_000, 34) and layout["calls"] == [28, 31, 34]
    sizes[34] = 10_000_001
    with pytest.raises(SystemExit):
        ex.export(row, "ffmpeg", {})
    assert not (layout["dest"] / "사용법" / "V99-예시.mp4").exists()


def test_readme_table_is_rebuilt_between_markers_only(ex, tmp_path, monkeypatch):
    """TC-VX-06 · README 파일 표는 자리 표시 두 줄 사이만 다시 쓴다(줄 끝 CRLF 그대로 · 두 번째는 바뀐 것 없음) · 파일은 git 밖이라 링크 없이 길이 · 크기만."""
    man = {
        ("사용법", "V01-예시"): {"kind": "사용법", "stem": "V01-예시", "title": "예시", "mp4": "docs/발표/영상/파일/사용법/V01-예시.mp4",
                              "duration_sec": 65.2, "bytes": 2_300_000, "recorded_at": "2026-10-18 20:00:00 KST"},
        ("발표", "P-V01-예시"): {"kind": "발표", "stem": "P-V01-예시", "title": "예시 — 자세히", "mp4": "docs/발표/영상/파일/발표/P-V01-예시.mp4",
                              "duration_sec": 125.8, "bytes": 5_500_000, "recorded_at": "2026-10-19 09:30:00 KST"},
    }
    table = ex.readme_table(man)
    assert "| V01 | 예시 — 자세히 | 1:05 · 2.3 MB | 2:06 · 5.5 MB | 2026-10-19 |" in table
    assert "](" not in table                                    # 링크 없음 — 공개 저장소에는 파일이 없다
    readme = tmp_path / "README.md"
    readme.write_bytes(f"# 머리\r\n\r\n{ex.TABLE_START}\r\n옛 표\r\n{ex.TABLE_END}\r\n\r\n꼬리\r\n".encode("utf-8"))
    monkeypatch.setattr(ex, "README", readme)
    assert ex.write_readme(man) is True
    text = readme.read_bytes().decode("utf-8")
    assert "옛 표" not in text and text.startswith("# 머리\r\n") and text.endswith("꼬리\r\n") and "\n" not in text.replace("\r\n", "")
    assert ex.write_readme(man) is False


def test_missing_h264_encoder_says_what_to_do(ex, monkeypatch):
    """TC-VX-07 · H.264 인코더가 없으면 막다른 길로 멈추지 않고 할 일(imageio-ffmpeg 설치 · QURIOUS_FFMPEG)을 알린다."""
    monkeypatch.delenv("QURIOUS_FFMPEG", raising=False)
    monkeypatch.setattr(ex.shutil, "which", lambda name: None)
    monkeypatch.setitem(__import__("sys").modules, "imageio_ffmpeg", None)
    with pytest.raises(SystemExit) as e:
        ex.find_h264_ffmpeg()
    assert "imageio-ffmpeg" in str(e.value) and "QURIOUS_FFMPEG" in str(e.value)


def test_local_videos_are_tracked_and_match_the_manifest(ex):
    """TC-VX-08 · 영상 mp4 · 그림은 git 에 둔다(.gitignore 에 막는 줄이 없다 — 2026-10-20 사용자 결정 「팀원이 받아 발표 자료에서 보게」 · 옛 10-19 결정은 git 밖) ·
    이 PC 에 내보낸 파일이 있으면 목록.json 과 하나씩 맞고(크기 · 지문) 편마다 10 MB 안 · 목록 밖 영상 파일이 없다 — 없는 PC 는 건너뜀."""
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pat in ("docs/발표/영상/파일/**/*.mp4", "docs/발표/영상/파일/**/*.jpg"):
        assert pat not in ignore, f".gitignore 에 {pat} 가 남아 있다 — 팀원이 받아도 발표 자료 영상이 비어 보인다"
    if not ex.MANIFEST.exists():
        pytest.skip("아직 내보낸 영상이 없다")
    if not any(p.suffix.lower() == ".mp4" for p in ex.DEST.rglob("*")):
        pytest.skip("이 PC 에는 내보낸 영상이 없다(내보내기 전 · 받기 전)")
    videos = json.loads(ex.MANIFEST.read_text(encoding="utf-8"))["videos"]
    listed = set()
    for e in videos:
        p = ROOT / e["mp4"]
        assert p.exists(), e["mp4"]
        assert p.stat().st_size == e["bytes"] <= ex.SIZE_LIMIT, e["mp4"]
        assert ex.file_sha(p) == e["sha"], e["mp4"]
        listed.add(p.resolve())
        if e.get("jpg"):
            assert (ROOT / e["jpg"]).exists(), e["jpg"]
            listed.add((ROOT / e["jpg"]).resolve())
        assert (ROOT / e["scene"]).exists(), e["scene"]
    on_disk = {p.resolve() for p in ex.DEST.rglob("*") if p.suffix.lower() in (".mp4", ".jpg", ".webm", ".mov")}
    assert on_disk == listed


def test_deck_videos_point_to_the_export_folder():
    """TC-VX-09 · 발표 자료의 영상 칸(src · poster)은 내보내기 폴더(../영상/파일/발표/)를 가리킨다 — 발표 PC 가 그 파일을 바로 재생한다(YAML 만이 아니라) ·
    내보낸 영상이 있을 때만 파일이 있는지 본다(내보내기 · 받기 전 PC 는 건너뜀) · 옛 media/ 폴더는 가리키지 않는다.
    2026-10-21 부터 고치는 원본은 발표자료-원본.html 이다 — 발표자료.html 은 그 원본에서 tools/deck/bundle_deck.py 가 만든 한 파일 판(영상이 파일 안에)."""
    deck = ROOT / "docs" / "발표" / "2차" / "발표자료-원본.html"
    html = deck.read_text(encoding="utf-8")
    refs = re.findall(r'<video[^>]*?\s(?:src|poster)="([^"]+)"', html)
    assert refs, "영상 칸이 하나도 없다"
    dest = ROOT / "docs" / "발표" / "영상" / "파일"
    local = dest.exists() and any(p.suffix.lower() == ".mp4" for p in dest.rglob("*"))
    for ref in refs:
        assert not ref.startswith("media/"), f"옛 media/ 폴더를 가리킨다: {ref}"
        assert ref.startswith("../영상/파일/발표/"), ref
        if local:
            assert (deck.parent / ref).resolve().exists(), ref
