"""통합 덱 영상 장의 겹침 층 — 큐 해석(이 파일 위쪽) · 마크업 · CSS · JS(아래쪽).

왜: 2026-11-11 강사님이 전체 발표를 30분 안으로 하라고 해서 이동원 파트를 절반으로 줄인다. 슬라이드를 보이고 영상을 또 보이면
같은 말을 두 번 하므로, **영상 위에 카드 · 말풍선 · 자막을 얹어 영상을 멈추고 설명**한다(설계: docs/phase-3/06-retrospective/이동원/30분-발표-재구성-설계.md).

큐 파일(videos/발표/큐/<영상 이름>.큐.yaml):
  video: <장면 stem>
  cues:
    - id: E1
      at: {kind: chapter|say|ring, n: 1}      # 녹화 기록(events.json)의 순번 — 이 이벤트가 뜨는 시각에 멈춘다
      type: card | bubble
      anchor: {kind: ring, n: 2}              # (말풍선) 붙일 강조 박스 — 없으면 화면 아래
      image: 이동원/그림/카드-신호기록.png       # (카드) 덱 HTML 기준 상대 경로 — 번들러가 한 파일 판에 넣는다
      title / text: 카드 · 말풍선 문구
      place: auto | right                      # (말풍선) 위치 — 기본 auto
      dx: 0                                    # (place: right) 오른쪽으로 더 비킬 px
      easy: 쉬운 말 한 줄                       # (말풍선) 「쉬운 말 · …」 로 덧붙는 풀이
      dur: 8                                   # (말풍선) 영상이 계속 재생되는 동안 뜨는 구간(초) — 기본 8
      pause: false                             # true 면 지나갈 때 영상을 멈춘다(기본 false — 사용자 11-11 「자동 멈춤은 별로」). 영상 시작 카드는 true
      enabled: true                            # 리허설에서 넘치면 false 로 끈다
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import yaml


def load_cue_file(path: Path) -> dict:
  return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _find(events_doc: dict, kind: str, n: int) -> dict | None:
  for e in events_doc.get("events", []):
    if e.get("kind") == kind and e.get("n") == n:
      return e
  return None


def resolve_cues(cue_doc: dict, events_doc: dict) -> list[dict]:
  """큐를 녹화 기록의 순번으로 시각으로 풀어 시각 순으로 돌려준다. 기록에 없는 순번이면 ValueError(조용히 무시하지 않는다)."""
  out: list[dict] = []
  for cue in cue_doc.get("cues", []):
    cid = cue.get("id", "?")
    at = cue.get("at") or {}
    ev = _find(events_doc, at.get("kind"), at.get("n"))
    if ev is None:
      raise ValueError(f"큐 {cid}: 녹화 기록에 {at.get('kind')} {at.get('n')} 이(가) 없다 — events.json 을 다시 확인")
    rect = None
    anchor = cue.get("anchor")
    if anchor:
      ring = _find(events_doc, anchor.get("kind", "ring"), anchor.get("n"))
      if ring is None or "rect" not in ring:
        raise ValueError(f"큐 {cid}: 붙일 강조 박스 {anchor} 가 녹화 기록에 없다")
      rect = list(ring["rect"])
    ctype = cue.get("type", "bubble")
    if ctype not in ("card", "bubble"):
      raise ValueError(f"큐 {cid}: type 은 card 또는 bubble 이어야 한다(받은 값: {ctype!r})")
    out.append({
      "id": cid, "t": ev["t0"], "type": ctype, "enabled": cue.get("enabled", True),
      "title": cue.get("title", ""), "text": cue.get("text", ""), "image": cue.get("image"), "rect": rect,
      "dx": cue.get("dx", 0), "place": cue.get("place", "auto"),
      "pause": bool(cue.get("pause", False)), "dur": cue.get("dur", 8), "easy": cue.get("easy", ""),   # 멈춤은 옵션(기본 안 멈춤) · 말풍선이 뜨는 구간(초) · 쉬운 말       # 말풍선 위치: auto(아래 → 모자라면 위) · right(강조 박스 오른쪽) — 다음에 누를 버튼을 가리지 않게
    })
  out.sort(key=lambda c: c["t"])
  on = [c for c in out if c["enabled"]]
  for a, b in zip(on, on[1:]):
    if a["t"] == b["t"]:
      raise ValueError(f"큐 {a['id']} 와 {b['id']} 가 같은 시각({a['t']}초)이다 — 하나는 뜨지 못한다. 다른 순번에 묶거나 enabled: false 로 끈다")
  return out


def captions(events_doc: dict) -> list[dict]:
  """자막(say) 이벤트 → [{t0, t1, text}]. 영상 재생 시각(currentTime)으로 띄운다."""
  return [{"t0": e["t0"], "t1": e["t1"], "text": e["text"]} for e in events_doc.get("events", []) if e["kind"] == "say"]


def chapter_cards(events_doc: dict) -> list[dict]:
  """장 카드 이벤트 → [{t0, t1, label, title, text}]."""
  return [{"t0": e["t0"], "t1": e["t1"], "label": e["label"], "title": e["title"], "text": e["text"]}
          for e in events_doc.get("events", []) if e["kind"] == "chapter"]


# ─────────────────────────────────────────────────────────────────────────────
# 겹침 층 마크업 · CSS · JS
# ─────────────────────────────────────────────────────────────────────────────

def player_markup(stem: str, cues: list[dict], caps: list[dict], chapters: list[dict], video_sec: float, vw: int, vh: int) -> str:
  """영상 칸(.video-wrap) 안에 넣을 겹침 층 HTML. 카드 이미지는 <img src> 상대 경로 — 번들러가 한 파일 판에 data 주소로 넣는다."""
  data = {"cues": cues, "caps": caps, "chapters": chapters, "video_sec": video_sec, "vw": vw, "vh": vh}
  blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
  e = html.escape
  cards = "".join(
    f'<div class="vp-card" data-cue="{e(c["id"])}" hidden>'
    f'<div class="vp-card-t">{e(c["title"])}</div>'
    f'<img src="{e(c["image"])}" alt="{e(c["title"])}">'
    f'<div class="vp-card-x">{e(c["text"])}</div></div>'
    for c in cues if c["type"] == "card" and c.get("image"))
  marks = "".join(f'<i style="left:{c["t"] / video_sec * 100:.2f}%"></i>' for c in cues if c["enabled"] and video_sec)
  return (f'<div class="vp-layer" data-vp="{e(stem)}">'
          f'<script type="application/json" class="vp-data">{blob}</script>'
          '<div class="vp-chap" hidden><div class="k"></div><div class="t"></div><div class="d"></div></div>'
          '<div class="vp-sub" hidden></div>'
          f'{cards}'
          '<div class="vp-bubble" hidden><b></b><span></span><em hidden></em></div>'
          '<div class="vp-hint" hidden>스페이스 ▶ 이어서</div>'
          f'<div class="vp-bar">{marks}</div>'
          '</div>')


PLAYER_CSS = """
/* 영상 겹침 층(자막 · 장 카드 · 카드 · 말풍선 · 멈춤 안내) — video_player.py. 영상 칸 안에서 영상 위에 얹는다 */
.vp-layer { position: absolute; inset: 0; pointer-events: none; z-index: 4; font-family: inherit; }
.vp-layer [hidden] { display: none !important; }
.vp-layer .vp-sub { position: absolute; left: 50%; bottom: 64px; transform: translateX(-50%); max-width: 78%; text-align: center;
  background: rgba(15,23,42,.86); color: #fff; font-size: 26px; line-height: 1.45; padding: 10px 22px; border-radius: 12px; font-weight: 600; }
.vp-layer .vp-chap { position: absolute; left: 50%; top: 14%; transform: translateX(-50%); width: 72%; text-align: center;
  background: rgba(15,23,42,.88); color: #fff; padding: 22px 30px; border-radius: 16px; }
.vp-layer .vp-chap .k { font-size: 20px; color: #a5b4fc; font-weight: 700; margin-bottom: 6px; }
.vp-layer .vp-chap .t { font-size: 38px; font-weight: 800; line-height: 1.3; }
.vp-layer .vp-chap .d { font-size: 22px; color: #cbd5e1; margin-top: 8px; line-height: 1.5; }
.vp-layer .vp-card { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); width: 86%; max-height: 92%;
  background: #fff; border-radius: 16px; box-shadow: 0 14px 50px rgba(0,0,0,.55); padding: 16px 22px 14px; text-align: center; overflow: hidden; }
.vp-layer .vp-card-t { font-size: 26px; font-weight: 800; color: #1e293b; margin-bottom: 8px; }
.vp-layer .vp-card img { display: block; margin: 0 auto; max-width: 100%; max-height: 520px; object-fit: contain; }
.vp-layer .vp-card-x { font-size: 20px; color: #475569; margin-top: 8px; line-height: 1.5; }
.vp-layer .vp-bubble { position: absolute; width: 560px; background: #fff; border: 3px solid #f59e0b; border-radius: 14px;
  box-shadow: 0 10px 30px rgba(0,0,0,.5); padding: 10px 16px; }
.vp-layer .vp-bubble b { display: block; font-size: 17px; color: #b45309; margin-bottom: 4px; }
.vp-layer .vp-bubble span { font-size: 22px; line-height: 1.5; color: #1e293b; font-weight: 600; display: block; }
.vp-layer .vp-bubble em { display: block; margin-top: 7px; padding-top: 6px; border-top: 1px dashed #e5c07b; font-style: normal; font-size: 18px; line-height: 1.45; color: #92400e; }
.vp-layer .vp-hint { position: absolute; right: 18px; top: 14px; background: #f59e0b; color: #1f2937; font-size: 22px; font-weight: 800;
  padding: 8px 18px; border-radius: 999px; }
.vp-layer .vp-bar { position: absolute; left: 0; right: 0; bottom: 22px; height: 0; }
.vp-layer .vp-bar i { position: absolute; top: -5px; width: 12px; height: 12px; margin-left: -6px; border-radius: 50%; background: #f59e0b; border: 2px solid #fff; }
"""

PLAYER_JS = r"""
(() => {
  /* 영상 겹침 층 — 자막 · 설명은 영상 재생 시각(currentTime)으로 띄운다(타이머 아님 → 멈춤 · 되감기 뒤에도 안 밀림).
     설명(큐)은 기본으로 영상을 멈추지 않는다(사용자 11-11) — 구간(dur초) 동안 말풍선으로 뜬다. pause: true 인 큐만 멈추고,
     영상 시작 전 카드도 멈춰 있다가 스페이스로 시작한다(→ · PageDown 은 영상을 틀지 않고 다음 장). 멈춤 큐에서는 →·PageDown·스페이스 = 이어서 재생. Shift+→ = 영상을 건너뛰고 다음 장. */
  const layers = [...document.querySelectorAll('.vp-layer')];
  if (!layers.length) return;
  const players = layers.map(layer => {
    const wrap = layer.closest('.video-wrap'), v = wrap.querySelector('video');
    const data = JSON.parse(layer.querySelector('.vp-data').textContent);
    const q = s => layer.querySelector(s);
    const P = { layer, wrap, v, data, slide: layer.closest('.slide'), last: -1, active: null, ov: null };
    const chap = q('.vp-chap'), sub = q('.vp-sub'), bubble = q('.vp-bubble'), hint = q('.vp-hint');
    const setCap = () => {
      if (P.active) { sub.hidden = true; chap.hidden = true; return; }      // 멈춘 카드 · 말풍선이 떠 있는 동안은 자막 · 장 카드를 숨긴다(겹침 방지)
      const now = v.currentTime;
      const c = data.caps.find(x => x.t0 <= now && now < x.t1);
      if (c) { sub.textContent = c.text; sub.hidden = false; } else { sub.hidden = true; }
      const h = data.chapters.find(x => x.t0 <= now && now < x.t1);
      if (h) { chap.querySelector('.k').textContent = h.label; chap.querySelector('.t').textContent = h.title;
        chap.querySelector('.d').textContent = h.text; chap.hidden = false; } else { chap.hidden = true; }
    };
    const placeBubble = (rect, place, dx) => {
      const W = v.clientWidth, H = v.clientHeight, bw = bubble.offsetWidth || 560, bh = bubble.offsetHeight || 90;
      const RES = 175;                               // 아래 자막 칸(두 줄)을 비워 둔다 — 말풍선이 자막을 가리지 않게
      if (!rect) { bubble.style.left = (W - bw) / 2 + 'px'; bubble.style.top = Math.max(8, H - bh - RES - 12) + 'px'; return; }
      const k = W / data.vw, [x, y, w, h] = rect.map(n => n * k);
      if (place === 'right') {                       // 강조 박스 오른쪽 빈 곳(자리가 없으면 왼쪽)
        let l = x + w + 18 + (dx || 0); if (l + bw > W - 8) l = Math.max(8, x - bw - 18);
        bubble.style.left = l + 'px'; bubble.style.top = Math.min(Math.max(8, y - 6), H - bh - RES) + 'px'; return;
      }
      let top = y + h + 14; if (top + bh > H - RES) top = Math.max(8, y - bh - 14);
      top = Math.max(8, Math.min(top, H - RES - bh));      // 강조 박스가 자막 칸 안쪽에 있어도 말풍선 아래 끝은 자막 칸 위에 둔다
      const left = Math.min(Math.max(8, x), W - bw - 8);
      bubble.style.left = left + 'px'; bubble.style.top = top + 'px';
    };
    const render = cue => {                          // 카드 또는 말풍선을 그린다(멈추지는 않는다)
      if (cue.type === 'card') { const c = layer.querySelector(`.vp-card[data-cue="${cue.id}"]`); if (c) c.hidden = false; return; }
      bubble.querySelector('b').textContent = cue.title || ''; bubble.querySelector('span').textContent = cue.text;
      const em = bubble.querySelector('em'); em.textContent = cue.easy ? '쉬운 말 · ' + cue.easy : ''; em.hidden = !cue.easy;
      bubble.hidden = false; placeBubble(cue.rect, cue.place, cue.dx);
    };
    P.hideCue = () => {
      layer.querySelectorAll('.vp-card').forEach(c => { c.hidden = true; });
      bubble.hidden = true; hint.hidden = true; P.active = null; P.ov = null;
    };
    P.showCue = cue => {                             // 멈추는 큐(시작 카드 · pause: true)
      P.hideCue(); P.active = cue; sub.hidden = true; chap.hidden = true;
      render(cue); hint.hidden = false; v.pause();
    };
    P.resume = () => { P.hideCue(); P.last = v.currentTime; v.play(); };
    P.tick = () => {
      const now = v.currentTime;
      if (now < P.last || now - P.last >= 1.0) { P.hideCue(); P.last = now < 0.1 ? -1 : now; }   // 되감기 · 건너뛰기는 멈춤 큐를 띄우지 않는다
      setCap();
      if (!P.active) {
        const pc = data.cues.find(c => c.enabled && c.pause && P.last < c.t && c.t <= now);
        if (pc) { P.showCue(pc); }
        else {                                       // 설명은 재생 시각만으로 정한다 — 구간 안이면 뜨고 지나면 사라진다
          const oc = data.cues.filter(c => c.enabled && !c.pause && c.t <= now && now < c.t + c.dur).pop() || null;
          if (!oc) { if (P.ov) { bubble.hidden = true; P.ov = null; } }
          else if (P.ov !== oc.id) { P.ov = oc.id; render(oc); }
        }
      }
      P.last = now;
    };
    const loop = () => { P.tick(); if (!v.paused && !v.ended) requestAnimationFrame(loop); };
    v.addEventListener('play', () => { if (P.active) { P.hideCue(); } requestAnimationFrame(loop); });
    v.addEventListener('timeupdate', P.tick);
    v.addEventListener('seeked', P.tick);
    v.addEventListener('focus', () => v.blur());     // 컨트롤을 마우스로 눌러도 키 입력이 덱 · 플레이어로 오게(검토: 포커스가 컨트롤에 있으면 keydown 이 안 온다)
    P.activate = () => {                             // 장이 열릴 때 — 처음 · 끝난 뒤면 처음으로 돌려 시작 카드를 먼저 띄운다. 중간이면 위치를 지킨다
      P.hideCue();
      if (v.ended || v.currentTime < 0.1) {
        P.last = -1; v.currentTime = 0; setCap();
        const first = data.cues.find(c => c.enabled && c.pause && c.t <= 0.05);
        if (first) { P.last = 0; P.showCue(first); }
      } else { P.last = v.currentTime; setCap(); }
    };
    new MutationObserver(() => { if (P.slide.classList.contains('on')) P.activate(); else P.hideCue(); })
      .observe(P.slide, { attributes: true, attributeFilter: ['class'] });
    if (P.slide.classList.contains('on')) P.activate();      // 영상 장에서 새로고침했을 때(덱이 이미 이 장을 열어 둔 경우)
    v.addEventListener('error', () => P.hideCue(), true);
    return P;
  });
  const current = () => players.find(p => p.slide.classList.contains('on') && !p.wrap.classList.contains('nofile'));
  addEventListener('keydown', e => {
    const p = current(); if (!p) return;
    const k = e.key, space = k === ' ' || k === 'Spacebar';
    if (!(space || k === 'ArrowRight' || k === 'PageDown')) return;      // ←·PageUp 은 덱 기본(이전 장)
    if (e.shiftKey && !space) return;                                    // Shift+→ · Shift+PageDown = 영상을 건너뛰고 다음 장(덱 기본)
    if (p.active) {
      if (p.active.t <= 0.05 && !space) return;                          // 시작 카드(영상을 아직 안 튼 상태): → · PageDown 은 덱 기본(다음 장) — 영상을 틀지 않고도 넘어간다(사용자 11-11)
      e.preventDefault(); e.stopImmediatePropagation(); p.resume(); return;
    }
    if (!space && p.v.paused && p.v.currentTime < 0.1) return;           // 아직 안 튼 영상(시작 카드를 껐을 때도 같음): → 는 다음 장
    if (p.v.ended) return;                                                 // 영상이 끝난 뒤는 덱 기본(다음 장)
    e.preventDefault(); e.stopImmediatePropagation();
    if (space) { p.v.paused ? p.v.play() : p.v.pause(); }                 // 재생 중 스페이스 = 일시정지(발표자가 직접 멈춰 설명)
    else if (p.v.paused) { p.v.play(); }                                  // 멈춰 있으면 → = 재생 · 재생 중 → 는 무시(실수로 장이 안 넘어가게)
  }, true);
})();
"""
