"""녹화 기록(자막 · 장 · 강조 박스)을 events.json 구조로 합친다 — 입출력 없는 순수 함수.

왜: 통합 덱의 영상 겹침 층(자막 · 카드 · 말풍선)은 영상 재생 시각에 묶인다. 깨끗한 영상(--clean)에서는 자막이 화면에
굽히지 않으므로, 녹화가 자막 · 장 · 강조 박스가 뜬 시각과 내용 · 좌표를 따로 남겨야 한다(2026-11-11 30분 발표 재구성 설계 4.1절).

모양: {"video_sec": 영상 길이, "vw": 녹화 화면 폭, "vh": 높이, "events": [
        {"kind": "chapter", "n": 1, "t0": 0.0, "t1": 3.2, "label": "…", "title": "…", "text": "…"},
        {"kind": "say",     "n": 1, "t0": 1.0, "t1": 4.0, "text": "…"},
        {"kind": "ring",    "n": 1, "t0": 2.0, "t1": 4.5, "rect": [x, y, w, h]} ]}
n 은 종류별 1부터(시각 순). 큐 파일이 「장 1」 「자막 3」 「강조 2」 처럼 이 순번으로 멈춤 지점을 가리킨다 — 다시 녹화해도 순번은 같다.
"""
from __future__ import annotations

MIN_SEC = 0.2          # record_demo 가 VTT 에 쓰는 기준과 같다 — 이보다 짧은 자막 · 장은 뺀다
_ORDER = {"chapter": 0, "say": 1, "ring": 2}   # 같은 시각이면 장 → 자막 → 강조


def build_events(subs, chapters, chapter_meta, rings, vw=1920, vh=1080, duration=0.0) -> dict:
  """subs · chapters: [(t0, t1, text)] · chapter_meta: [(label, title, text)](장 순서 그대로) · rings: [(t0, t1, (x, y, w, h))]."""
  raw: list[dict] = []
  kept_chapters = [(a, b, t) for a, b, t in chapters if b - a > MIN_SEC]
  # chapter_meta 는 녹화된 장 전부의 메타 — 짧아서 버려진 장이 있으면 순서를 맞추려고 같은 조건으로 거른다
  meta = [m for (a, b, _), m in zip(chapters, chapter_meta) if b - a > MIN_SEC]
  for (a, b, title), (label, mtitle, text) in zip(kept_chapters, meta):
    raw.append({"kind": "chapter", "t0": a, "t1": b, "label": label, "title": mtitle or title, "text": text})
  for a, b, text in subs:
    if b - a > MIN_SEC:
      raw.append({"kind": "say", "t0": a, "t1": b, "text": text})
  for a, b, (x, y, w, h) in rings:
    raw.append({"kind": "ring", "t0": a, "t1": b, "rect": [x, y, w, h]})
  raw.sort(key=lambda e: (e["t0"], _ORDER[e["kind"]]))
  count: dict[str, int] = {}
  events = []
  for e in raw:
    count[e["kind"]] = count.get(e["kind"], 0) + 1
    ev = {"kind": e["kind"], "n": count[e["kind"]], "t0": round(e["t0"], 2), "t1": round(e["t1"], 2)}
    ev.update({k: v for k, v in e.items() if k not in ("kind", "t0", "t1")})
    events.append(ev)
  return {"video_sec": round(duration, 2), "vw": vw, "vh": vh, "events": events}
