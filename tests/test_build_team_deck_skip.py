"""tools/deck/build_team_deck.py — 30분 발표 판: 이동원 슬라이드 일부를 덱에서 빼고 영상 장에 겹침 층을 넣는 조립 시험.

왜: 이동원 파트를 절반으로 줄이려고(2026-11-11 설계 3절) 슬라이드 1 · 3 · 4 · 6 · 7 · 9장만 덱에 남기고, 9장 뒤에 영상 E → 영상 C 를
둔다. 원본 `이동원/발표자료.html` 은 그대로 둔다(내용은 발표에서 생략하며 넘긴다는 사용자 결정).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEEP = (1, 3, 4, 6, 7, 9)
SKIPPED = (2, 5, 8, 10, 11, 12, 13, 14, 15)


@pytest.fixture(scope="module")
def bt():
    spec = importlib.util.spec_from_file_location("build_team_deck", ROOT / "tools" / "deck" / "build_team_deck.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_team_deck"] = mod          # dataclass 가 자기 모듈을 찾을 수 있게 등록한다
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plan(bt):
    return bt.make_plan()


def test_skipped_slides_not_in_deck(bt, plan):
    p = bt.read_personal("이동원")
    want = [p.slides[i - 1].title for i in KEEP]
    got = [f.title for f in plan.frames if f.kind == "slide" and f.owner == "이동원"]
    assert got == want


def test_video_order_e_then_c_after_slide_9(bt, plan):
    p = bt.read_personal("이동원")
    nine = p.slides[9 - 1].title
    idx = next(i for i, f in enumerate(plan.frames) if f.kind == "slide" and f.owner == "이동원" and f.title == nine)
    assert plan.frames[idx + 1].kind == "video" and plan.frames[idx + 1].title.startswith("P-이동원-E-")
    assert plan.frames[idx + 2].kind == "video" and plan.frames[idx + 2].title.startswith("P-이동원-C-")


def test_expected_count_matches_frames(bt, plan):
    assert bt.verify(plan, bt.render(plan)) == []


def test_remaining_slides_do_not_reference_skipped_numbers(bt):
    # 남은 슬라이드에 빠진 장을 가리키는 문구(「2 ~ 5장」 등)가 있으면 조립기의 TEXT_PATCH 표가 덱 쪽을 바꿔야 한다(원본은 불변)
    p = bt.read_personal("이동원")
    patched = {old for (name, _i), lst in bt.TEXT_PATCH.items() if name == "이동원" for old, _ in lst}
    refs = []
    for i in KEEP:
        text = re.sub(r"<[^>]+>", " ", p.slides[i - 1].html)
        for m in re.finditer(r"(?<![\d.])(\d{1,2})(?:\s*(?:~|·)\s*\d{1,2})*\s*장", text):
            nums = [int(n) for n in re.findall(r"\d+", m.group(0))]
            if any(n in SKIPPED for n in nums) and m.group(0) not in patched:
                refs.append((i, m.group(0)))
    assert refs == [], f"치환표에 없는, 빠진 장을 가리키는 문구: {refs}"


def test_text_patch_applied_to_deck_slide_1(plan):
    f = next(f for f in plan.frames if f.kind == "slide" and f.owner == "이동원")
    assert "2 ~ 5장" not in f.html and "8 ~ 15장" not in f.html


def test_video_slides_have_player_layer(plan):
    html_e = next(f.html for f in plan.frames if f.kind == "video" and "P-이동원-E-" in f.title)
    html_c = next(f.html for f in plan.frames if f.kind == "video" and "P-이동원-C-" in f.title)
    for h in (html_e, html_c):
        assert 'class="vp-layer"' in h and 'class="vp-data"' in h
    assert 'class="vp-card"' in html_e and "이동원/그림/카드-신호기록.png" in html_e
    assert "이동원/그림/카드-일지구조.png" in html_c


def test_player_layer_fails_when_events_missing(bt, tmp_path, monkeypatch):
    # 큐 파일은 있는데 녹화 기록(events.json)이 없으면 조용히 겹침 층 없이 빌드하지 않고 멈춘다(최종 검토)
    cues, files = tmp_path / "큐", tmp_path / "파일"
    cues.mkdir(); files.mkdir()
    (cues / "X.큐.yaml").write_text("video: X\ncues: []\n", encoding="utf-8")
    monkeypatch.setattr(bt, "CUES_DIR", cues)
    monkeypatch.setattr(bt, "FILES", files)
    with pytest.raises(SystemExit):
        bt.player_layer("X")
    assert bt.player_layer("Y") == ""                       # 큐 파일이 없으면 예전 모양 그대로


def test_skip_slides_out_of_range_fails(bt, monkeypatch):
    monkeypatch.setattr(bt, "SKIP_SLIDES", {"이동원": {2, 99}})
    with pytest.raises(SystemExit):
        bt.make_plan()


def test_divider_and_cover_count_only_kept_slides(bt, plan):
    # 사용자 11-11: 이동원 구분 장의 슬라이드 장 수 · 대본 시간이 덱에서 뺀 장까지 세면 안 된다(표지도 같음)
    div = next(f.html for f in plan.frames if f.kind == "divider" and f.owner == "이동원")
    assert '<div class="v">6장</div>' in div, "이동원 구분 장의 슬라이드 수는 덱에 남은 6장이어야 한다"
    assert bt.fmt_dur(225) in div, "이동원 대본 시간은 남은 6장의 노트 합(225초)이어야 한다"
    n_slides = sum(1 for f in plan.frames if f.kind == "slide")
    cover = next(f.html for f in plan.frames if f.kind == "cover")
    assert f"슬라이드 {n_slides}장" in cover


def test_divider_lists_videos_in_presentation_order(plan):
    # 구분 장의 영상 표기도 발표 순서(E → C)여야 한다 — 장면 이름 순(C → E)으로 나오면 순서가 틀려 보인다
    div = next(f.html for f in plan.frames if f.kind == "divider" and f.owner == "이동원")
    assert div.index("E편") < div.index("C편")


def test_cover_intro_describes_the_project_and_keeps_roles(bt, plan):
    # 사용자 11-11: 표지의 「3차 프로젝트 발표」 대신 Qurious 3차 프로젝트(투자 인디케이터)의 핵심 소개글. 아래 담당자별 역할은 그대로
    cover = next(f.html for f in plan.frames if f.kind == "cover")
    assert '<p class="one">3차 프로젝트 발표</p>' not in cover
    assert "나만의 투자 인디케이터" in cover and "TradingView" in cover and "LEAN" in cover and "모의계좌" in cover
    for name in bt.ORDER:
        assert f"{name} · {bt.ROLES[name]}" in cover          # 담당자별 역할 칩은 그대로
