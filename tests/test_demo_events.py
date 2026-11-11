"""tools/demo/events_log.py — 녹화 기록(자막 · 장 · 강조)을 events.json 구조로 합치는 순수 함수 시험.

왜: 통합 덱의 영상 겹침 층(자막 · 카드 · 말풍선)이 영상 재생 시각에 묶이려면, 녹화가 자막 · 장 · 강조 박스가 뜬 시각과
좌표를 남겨야 한다(2026-11-11 30분 발표 재구성 설계 4.1절). 이 시험은 그 합치기만 본다(브라우저 · 녹화 없음).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("events_log", ROOT / "tools" / "demo" / "events_log.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_events_orders_by_time_and_numbers_per_kind():
    ev = _load().build_events(
        subs=[(1.0, 3.0, "가"), (5.0, 6.0, "나")],
        chapters=[(0.0, 2.0, "제목")],
        chapter_meta=[("1 / 3 · 목적", "제목", "설명")],
        rings=[(2.0, 4.5, (10, 20, 30, 40))],
        vw=1920, vh=1080, duration=7.0,
    )
    assert [(e["kind"], e["n"], e["t0"]) for e in ev["events"]] == [
        ("chapter", 1, 0.0), ("say", 1, 1.0), ("ring", 1, 2.0), ("say", 2, 5.0)]
    ring = next(e for e in ev["events"] if e["kind"] == "ring")
    assert ring["rect"] == [10, 20, 30, 40]
    chap = next(e for e in ev["events"] if e["kind"] == "chapter")
    assert chap["label"] == "1 / 3 · 목적" and chap["title"] == "제목" and chap["text"] == "설명"
    assert (ev["video_sec"], ev["vw"], ev["vh"]) == (7.0, 1920, 1080)


def test_build_events_drops_tiny_events():
    # 0.2초 이하 자막은 뺀다 — record_demo 가 VTT 에 쓰는 기준과 같다(순번도 남은 것끼리 다시 센다)
    ev = _load().build_events(
        subs=[(1.0, 1.1, "너무 짧음"), (2.0, 4.0, "남김")],
        chapters=[], chapter_meta=[], rings=[], vw=1920, vh=1080, duration=5.0,
    )
    says = [e for e in ev["events"] if e["kind"] == "say"]
    assert [(e["n"], e["text"]) for e in says] == [(1, "남김")]
