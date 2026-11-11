"""tools/deck/video_player.py — 큐 파일(YAML)을 녹화 기록(events.json)의 순번에 묶어 시각으로 풀어내는 순수 함수 시험.

왜: 통합 덱 영상 장의 멈춤 · 카드 · 말풍선은 「장 1 · 자막 3 · 강조 2」 같은 순번에 묶인다(절대 시각이 아님) —
영상을 다시 녹화해도 큐 파일은 그대로 쓰려고(2026-11-11 30분 발표 재구성 설계 4.3 · 8-1절).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("video_player", ROOT / "tools" / "deck" / "video_player.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EVENTS = {
    "video_sec": 10.0, "vw": 1280, "vh": 720,
    "events": [
        {"kind": "chapter", "n": 1, "t0": 0.0, "t1": 2.0, "label": "1 / 3 · 목적", "title": "제목", "text": "설명"},
        {"kind": "say", "n": 1, "t0": 1.0, "t1": 4.0, "text": "첫 자막"},
        {"kind": "ring", "n": 1, "t0": 2.0, "t1": 3.5, "rect": [10, 20, 30, 40]},
        {"kind": "say", "n": 2, "t0": 4.0, "t1": 9.0, "text": "둘째 자막"},
    ],
}


def test_resolve_cues_uses_anchor_time_and_ring_rect():
    vp = _load()
    doc = {"video": "x", "cues": [
        {"id": "E1", "at": {"kind": "chapter", "n": 1}, "type": "card", "image": "그림/a.png", "title": "카드", "text": "설명"},
        {"id": "E2", "at": {"kind": "say", "n": 1}, "type": "bubble", "anchor": {"kind": "ring", "n": 1}, "text": "말풍선"},
    ]}
    cues = vp.resolve_cues(doc, EVENTS)
    assert [c["t"] for c in cues] == [0.0, 1.0]
    assert cues[0]["type"] == "card" and cues[0]["image"] == "그림/a.png"
    assert cues[1]["rect"] == [10, 20, 30, 40] and cues[1]["text"] == "말풍선"


def test_resolve_cues_unknown_anchor_raises():
    vp = _load()
    doc = {"video": "x", "cues": [{"id": "E9", "at": {"kind": "say", "n": 9}, "type": "bubble", "text": "없음"}]}
    with pytest.raises(ValueError, match="E9"):
        vp.resolve_cues(doc, EVENTS)


def test_resolve_cues_keeps_disabled_flag():
    vp = _load()
    doc = {"video": "x", "cues": [
        {"id": "A", "at": {"kind": "say", "n": 1}, "type": "bubble", "text": "켜짐"},
        {"id": "B", "at": {"kind": "say", "n": 2}, "type": "bubble", "text": "꺼짐", "enabled": False},
    ]}
    cues = vp.resolve_cues(doc, EVENTS)
    assert [(c["id"], c["enabled"]) for c in cues] == [("A", True), ("B", False)]


def test_captions_and_chapter_cards_from_events():
    vp = _load()
    assert vp.captions(EVENTS) == [{"t0": 1.0, "t1": 4.0, "text": "첫 자막"}, {"t0": 4.0, "t1": 9.0, "text": "둘째 자막"}]
    assert vp.chapter_cards(EVENTS) == [{"t0": 0.0, "t1": 2.0, "label": "1 / 3 · 목적", "title": "제목", "text": "설명"}]


CUE_DIR = ROOT / "docs" / "phase-3" / "06-retrospective" / "videos" / "발표" / "큐"
REC_DIR = ROOT / "docs" / "phase-3" / "06-retrospective" / "videos" / "파일" / "발표"


@pytest.mark.parametrize("stem,count,cards", [
    ("P-이동원-E-신호순위-근거-상세", 12, 1),
    ("P-이동원-C-일지판고정", 9, 1),
])
def test_real_cue_files_resolve(stem, count, cards):
    import json
    vp = _load()
    cues = vp.resolve_cues(vp.load_cue_file(CUE_DIR / f"{stem}.큐.yaml"),
                           json.loads((REC_DIR / f"{stem}.events.json").read_text(encoding="utf-8")))
    assert len(cues) == count
    assert sum(1 for c in cues if c["type"] == "card") == cards
    assert cues[0]["t"] == 0.0 and cues[0]["type"] == "card" and cues[0]["pause"]   # 카드가 영상 시작에 먼저 뜨고 멈춰 있다
    assert all(not c["pause"] for c in cues[1:]), "자동 멈춤은 기본이 아니다(사용자 11-11) — 시작 카드만 멈춘다"
    assert all(c["easy"] for c in cues if c["type"] == "bubble" and c["id"] not in ("E10", "E12")), "쉬운 말이 빠진 설명이 있다"
    for c in cues:
        if c["type"] == "bubble" and c["id"] not in ("E2", "C9"):
            assert c["rect"] is not None, f"{c['id']} 말풍선이 강조 박스에 붙지 않았다"


@pytest.mark.parametrize("stem", ["P-이동원-E-신호순위-근거-상세", "P-이동원-C-일지판고정"])
def test_cue_text_avoids_forbidden_claims(stem):
    # 영상 C 장면 파일의 「말하지 않는 것」 — 성과 · 수익 · 검증됐다 · 절대 · 증권사 주문
    vp = _load()
    doc = vp.load_cue_file(CUE_DIR / f"{stem}.큐.yaml")
    text = " ".join(str(c.get("title", "")) + " " + str(c.get("text", "")) for c in doc["cues"])
    for bad in ("성과를", "성과가 좋", "수익", "검증됐", "절대", "증권사에 주문", "주문을 냈"):   # 「성과로 읽지 않습니다」 는 말해도 된다(장면 파일 자막과 같음)
        assert bad not in text, f"큐 문구에 금지 낱말 「{bad}」"


def test_resolve_cues_passes_place_option():
    # 말풍선 위치 옵션(place: right 등) — 기본은 auto. 다음에 누를 버튼을 말풍선이 가리지 않게 큐마다 정할 수 있다
    vp = _load()
    doc = {"video": "x", "cues": [
        {"id": "A", "at": {"kind": "say", "n": 1}, "type": "bubble", "anchor": {"kind": "ring", "n": 1}, "text": "t", "place": "right"},
        {"id": "B", "at": {"kind": "say", "n": 2}, "type": "bubble", "text": "t"},
    ]}
    cues = vp.resolve_cues(doc, EVENTS)
    assert [(c["id"], c["place"]) for c in cues] == [("A", "right"), ("B", "auto")]
    assert [c["dx"] for c in cues] == [0, 0]          # dx(오른쪽으로 더 비킬 px)는 기본 0


def test_resolve_cues_rejects_duplicate_time_and_unknown_type():
    # 같은 시각에 켜진 큐가 둘이면 둘째가 안 뜬다 · type 오타는 조용히 말풍선이 된다 → 둘 다 빌드에서 멈춘다(최종 검토)
    vp = _load()
    dup = {"video": "x", "cues": [
        {"id": "A", "at": {"kind": "say", "n": 1}, "type": "bubble", "text": "a"},
        {"id": "B", "at": {"kind": "say", "n": 1}, "type": "bubble", "text": "b"},
    ]}
    with pytest.raises(ValueError, match="같은 시각"):
        vp.resolve_cues(dup, EVENTS)
    typo = {"video": "x", "cues": [{"id": "T", "at": {"kind": "say", "n": 1}, "type": "bubbel", "text": "t"}]}
    with pytest.raises(ValueError, match="T"):
        vp.resolve_cues(typo, EVENTS)
    off = {"video": "x", "cues": [
        {"id": "A", "at": {"kind": "say", "n": 1}, "type": "bubble", "text": "a"},
        {"id": "B", "at": {"kind": "say", "n": 1}, "type": "bubble", "text": "b", "enabled": False},
    ]}
    assert len(vp.resolve_cues(off, EVENTS)) == 2          # 꺼진 큐는 같은 시각이어도 된다


def test_resolve_cues_default_does_not_pause_and_has_duration_and_easy():
    # 사용자 11-11: 자동 멈춤은 기본이 아니다 — 큐는 영상이 재생되는 동안 dur 초 뜨는 설명이고, 쉬운 말(easy)을 함께 싣는다
    vp = _load()
    doc = {"video": "x", "cues": [
        {"id": "A", "at": {"kind": "say", "n": 1}, "type": "bubble", "text": "t"},
        {"id": "B", "at": {"kind": "say", "n": 2}, "type": "bubble", "text": "t", "pause": True, "dur": 5, "easy": "쉬운 말"},
    ]}
    a, b = vp.resolve_cues(doc, EVENTS)
    assert (a["pause"], a["dur"], a["easy"]) == (False, 8, "")
    assert (b["pause"], b["dur"], b["easy"]) == (True, 5, "쉬운 말")
