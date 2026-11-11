"""한 파일 판 통합 덱의 영상 겹침 층 검증 — 빈 폴더에 한 파일만 복사해 열어 본다(2026-11-11 설계 6절 · 사용자 「발표 자료만 받아도 이미지와 영상이 정상」).

쓰는 법:
  python -I tools/deck/verify_deck_player.py <한 파일 판.html> [--shots <캡처 폴더>] [--keep-copy]
  → 파일을 임시 빈 폴더에 복사해서 그 한 파일만 열고, 항목마다 ✅/❌ 를 찍는다. 하나라도 ❌ 면 종료 코드 1.

검사:
  ① 외부 요청 0 · 페이지 오류 0 · 영상 모두 blob 으로 풀림 · 카드 이미지(숨겨져 있어도) 디코드 · 슬라이드 그림 깨짐 0
  ② 영상 장에 열리면 카드가 먼저 뜨고 영상은 멈춰 있다 → 스페이스로 시작(장 번호 그대로)
  ③ 재생 중 → · PageDown 은 무시 · 스페이스는 일시정지/재생 · 영상이 끝난 뒤 → 는 다음 장
  ④ 자막 정합 — 영상 시각을 앞뒤로 건너뛰어도 그 시각의 자막이 기록과 같다
  ⑤ 설명(큐) — 영상이 **멈추지 않고** 재생되는 동안 구간 안에서 말풍선(설명 + 쉬운 말)이 뜨고 구간이 지나면 사라진다 · 영상 칸 안(1920×1080 · 1280×720)
  ⑥ 최종 검토에서 나온 경우 — 영상 컨트롤을 마우스로 눌러도 키가 먹는다 · 더블클릭 전체 화면 막힘 · ← 로 나갔다 돌아와도 위치 유지 · 새로고침 직후 카드가 먼저 뜬다
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> bool:
  results.append((bool(ok), msg))
  print(("✅ " if ok else "❌ ") + msg)
  return bool(ok)


JS_IDX = "() => [...document.querySelectorAll('#deck > .slide')].findIndex(s => s.classList.contains('on'))"
WAIT_BLOBS = "() => [...document.querySelectorAll('video')].every(v => v.src && v.readyState >= 1)"


def goto_slide(page, target: int) -> None:
  """키로 target(0부터) 장까지 이동한다 — Shift+→ 는 영상 장도 건너뛰고 지나간다."""
  page.keyboard.press("Home")
  page.wait_for_timeout(150)
  for _ in range(target):
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_timeout(60)
  page.wait_for_timeout(400)


def seek(page, sel: str, t: float) -> None:
  page.evaluate("""([sel, t]) => new Promise(res => { const v = document.querySelector(sel); v.pause();
      const done = () => { v.removeEventListener('seeked', done); setTimeout(res, 180); };
      v.addEventListener('seeked', done); v.currentTime = t; })""", [sel, t])


def verify_video(page, shots: Path | None, idx: int, stem_key: str) -> None:
  sel = f'#deck > .slide:nth-child({idx + 1}) video'            # nth-child 는 #deck 안에서 1부터(표지가 첫째)
  layer_sel = f'#deck > .slide:nth-child({idx + 1}) .vp-layer'
  bubble = f"{layer_sel} .vp-bubble"
  data = page.evaluate(f"() => JSON.parse(document.querySelector('{layer_sel} .vp-data').textContent)")
  goto_slide(page, idx)
  check(page.evaluate(JS_IDX) == idx, f"[{stem_key}] 영상 장으로 이동(장 {idx + 1})")

  first = data["cues"][0]
  card_visible = page.evaluate(f"() => !document.querySelector('{layer_sel} .vp-card[data-cue=\"{first['id']}\"]').hidden")
  check(card_visible and page.evaluate(f"() => document.querySelector('{sel}').paused"),
        f"[{stem_key}] 장이 열리면 카드({first['id']})가 먼저 뜨고 영상은 멈춰 있음")
  if shots:
    page.screenshot(path=str(shots / f"{stem_key}-card.png"))

  # 영상을 틀지 않아도 넘어갈 수 있어야 한다(사용자 11-11) — 시작 카드 상태에서 → · PageDown 은 다음 장, ← · PageUp 으로 돌아오면 카드가 다시 먼저 뜬다
  for nxt, prv in (("ArrowRight", "ArrowLeft"), ("PageDown", "PageUp")):
    page.keyboard.press(nxt)
    page.wait_for_timeout(400)
    went = page.evaluate(JS_IDX) == idx + 1
    page.keyboard.press(prv)
    page.wait_for_timeout(500)
    back = page.evaluate(f"() => document.querySelector('{layer_sel} .vp-card[data-cue=\"{first['id']}\"]').hidden === false") and page.evaluate(JS_IDX) == idx
    check(went and back, f"[{stem_key}] 영상을 틀지 않아도 {nxt} 로 다음 장 · {prv} 로 돌아오면 카드가 다시 먼저 뜸")

  page.keyboard.press("Space")
  page.wait_for_timeout(700)
  playing = page.evaluate(f"() => !document.querySelector('{sel}').paused")
  hidden = page.evaluate(f"() => document.querySelector('{layer_sel} .vp-card[data-cue=\"{first['id']}\"]').hidden")
  check(playing and hidden and page.evaluate(JS_IDX) == idx, f"[{stem_key}] 스페이스 → 카드 닫힘 · 재생 시작 · 장 번호 그대로")

  page.keyboard.press("ArrowRight")
  page.keyboard.press("PageDown")
  page.wait_for_timeout(300)
  check(page.evaluate(JS_IDX) == idx and page.evaluate(f"() => !document.querySelector('{sel}').paused"),
        f"[{stem_key}] 재생 중 →·PageDown 은 무시(장 번호 그대로 · 계속 재생)")
  page.keyboard.press("Space")
  page.wait_for_timeout(250)
  was_paused = page.evaluate(f"() => document.querySelector('{sel}').paused")
  page.keyboard.press("Space")
  page.wait_for_timeout(250)
  check(was_paused and page.evaluate(f"() => !document.querySelector('{sel}').paused"), f"[{stem_key}] 재생 중 스페이스 = 일시정지 · 다시 누르면 재생")

  # ④ 자막 정합 — 앞뒤로 건너뛰며 그 시각의 자막이 기록과 같은지
  caps = data["caps"]
  order = [caps[i] for i in range(0, len(caps), 2)]
  order = order + list(reversed(order))[1:]                       # 앞으로 갔다가 뒤로 되감기
  bad = []
  for c in order:
    t = c["t0"] + 0.05
    seek(page, sel, t)
    got = page.evaluate(f"() => {{ const s = document.querySelector('{layer_sel} .vp-sub'); return s.hidden ? null : s.textContent; }}")
    if got != c["text"]:
      bad.append((round(t, 2), got))
  check(not bad, f"[{stem_key}] 자막 정합 {len(order)}곳(앞뒤 건너뛰기) — 어긋남 {bad[:2]}")

  # ⑤ 설명(큐) — 멈추지 않고 재생되는 동안 구간 안에서 뜬다
  overlays = [c for c in data["cues"] if c["type"] == "bubble" and c["enabled"] and not c["pause"]]
  for cue in overlays:
    seek(page, sel, max(0.0, cue["t"] - 0.4))
    page.evaluate(f"() => document.querySelector('{sel}').play()")
    page.wait_for_timeout(1300)
    shown = page.evaluate(f"() => {{ const b = document.querySelector('{bubble}'); return b.hidden ? null : b.querySelector('b').textContent; }}")
    running = page.evaluate(f"() => !document.querySelector('{sel}').paused")
    ok_pos = True
    page.evaluate(f"() => document.querySelector('{sel}').pause()")
    for vp in ((1920, 1080), (1280, 720)):
      page.set_viewport_size({"width": vp[0], "height": vp[1]})
      page.wait_for_timeout(250)
      inside = page.evaluate(f"""() => {{ const b = document.querySelector('{bubble}').getBoundingClientRect();
        const v = document.querySelector('{sel}').getBoundingClientRect();
        return b.left >= v.left - 2 && b.right <= v.right + 2 && b.top >= v.top - 2 && b.bottom <= v.bottom + 2; }}""")
      ok_pos = ok_pos and inside
      if shots and vp == (1920, 1080):
        page.screenshot(path=str(shots / f"{stem_key}-{cue['id']}.png"))
    page.set_viewport_size({"width": 1920, "height": 1080})
    check(shown == cue["title"] and running, f"[{stem_key}] 설명 {cue['id']} — 영상이 멈추지 않고 재생되는 중에 뜸(제목 {shown!r})")
    check(ok_pos, f"[{stem_key}] 설명 {cue['id']} — 영상 칸 안(1920×1080 · 1280×720)")
    seek(page, sel, cue["t"] + 0.6)                          # 자막이 같이 떠 있는 시각 — 말풍선이 자막을 가리지 않는지
    clear = page.evaluate(f"""() => {{ const b = document.querySelector('{bubble}'), s = document.querySelector('{layer_sel} .vp-sub');
      if (b.hidden || s.hidden) return true; return b.getBoundingClientRect().bottom <= s.getBoundingClientRect().top + 2; }}""")
    check(clear, f"[{stem_key}] 설명 {cue['id']} — 아래 자막을 가리지 않음")
    seek(page, sel, cue["t"] + cue["dur"] + 0.6)
    after = page.evaluate(f"() => {{ const b = document.querySelector('{bubble}'); return b.hidden ? null : b.querySelector('b').textContent; }}")
    check(after != cue["title"], f"[{stem_key}] 설명 {cue['id']} — 구간({cue['dur']}초)이 지나면 사라짐")

  # 멈춤 옵션(pause: true)이 있는 큐 — 지나가면 멈추고 스페이스로 이어진다
  for cue in [c for c in data["cues"] if c["enabled"] and c["pause"] and c["t"] > 0.1]:
    seek(page, sel, max(0.0, cue["t"] - 0.45))
    page.evaluate(f"() => document.querySelector('{sel}').play()")
    page.wait_for_function(f"() => document.querySelector('{sel}').paused", timeout=4000)
    page.keyboard.press("Space")
    page.wait_for_timeout(250)
    check(page.evaluate(f"() => !document.querySelector('{sel}').paused") and page.evaluate(JS_IDX) == idx,
          f"[{stem_key}] 멈춤 큐 {cue['id']} — 멈춘 뒤 스페이스로 이어서 재생")

  # ⑥ 최종 검토에서 나온 경우
  seek(page, sel, 12.0)
  page.evaluate(f"() => document.querySelector('{sel}').play()")
  page.wait_for_timeout(500)
  box = page.evaluate(f"() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }}")
  page.mouse.click(box[0] + box[2] * 0.55, box[1] + box[3] - 20)          # 영상 컨트롤(진행 막대 근처)을 마우스로 누른다
  page.wait_for_timeout(300)
  s0 = page.evaluate(f"() => document.querySelector('{sel}').paused")
  page.keyboard.press("Space")
  page.wait_for_timeout(300)
  s1 = page.evaluate(f"() => document.querySelector('{sel}').paused")
  check(s0 != s1, f"[{stem_key}] 영상 컨트롤을 마우스로 눌러도 스페이스가 먹는다(일시정지 {s0} → {s1})")
  page.keyboard.press("ArrowRight")
  page.wait_for_timeout(200)
  check(page.evaluate(JS_IDX) == idx, f"[{stem_key}] 마우스로 누른 뒤에도 → 가 영상 장을 넘기지 않는다")

  page.mouse.dblclick(box[0] + box[2] / 2, box[1] + box[3] / 2)
  page.wait_for_timeout(500)
  fs = page.evaluate("() => document.fullscreenElement ? document.fullscreenElement.tagName : null")
  check(fs is None, f"[{stem_key}] 영상 더블클릭이 영상만 전체 화면으로 만들지 않는다({fs})")
  if fs:
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

  seek(page, sel, 20.0)
  page.keyboard.press("ArrowLeft")
  page.wait_for_timeout(300)
  went_back = page.evaluate(JS_IDX) == idx - 1
  page.keyboard.press("Shift+ArrowRight")                            # 앞 장이 영상 장일 수 있어(C 앞은 E) 영상을 건너뛰는 키로 돌아온다
  page.wait_for_timeout(500)
  ct = page.evaluate(f"() => document.querySelector('{sel}').currentTime")
  check(went_back and page.evaluate(JS_IDX) == idx and abs(ct - 20.0) < 0.6,
        f"[{stem_key}] ← 로 나갔다 돌아와도 영상 위치 유지({ct:.1f}초 · 0초로 안 돌아감)")

  # ③ 영상이 끝난 뒤 → 는 다음 장
  dur = page.evaluate(f"() => document.querySelector('{sel}').duration")
  seek(page, sel, dur - 0.25)
  page.evaluate(f"() => document.querySelector('{sel}').play()")
  page.wait_for_function(f"() => document.querySelector('{sel}').ended", timeout=5000)
  page.keyboard.press("ArrowRight")
  page.wait_for_timeout(400)
  check(page.evaluate(JS_IDX) == idx + 1, f"[{stem_key}] 영상이 끝난 뒤 → 는 다음 장으로(장 {idx + 1} → {idx + 2})")


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("deck", type=Path)
  ap.add_argument("--shots", type=Path, default=None)
  ap.add_argument("--keep-copy", action="store_true")
  args = ap.parse_args()
  work = Path(tempfile.mkdtemp(prefix="deck-alone-"))               # 빈 폴더 — 이 파일 하나만 둔다
  copy = work / "deck.html"
  shutil.copyfile(args.deck, copy)
  assert [p.name for p in work.iterdir()] == ["deck.html"]
  if args.shots:
    args.shots.mkdir(parents=True, exist_ok=True)

  external: list[str] = []
  errors: list[str] = []
  with sync_playwright() as p:
    browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.on("request", lambda r: external.append(r.url) if not r.url.startswith(("file:", "data:", "blob:")) else None)
    page.on("pageerror", lambda e: errors.append(str(e)[:160]))
    page.goto(copy.as_uri())
    page.wait_for_function(WAIT_BLOBS, timeout=120000)
    info = page.evaluate("""() => {
      const slides = [...document.querySelectorAll('#deck > .slide')];
      const vids = [...document.querySelectorAll('video')];
      const imgs = [...document.querySelectorAll('img')];
      const cardImgs = [...document.querySelectorAll('.vp-card img')];
      return { slides: slides.length, videos: vids.length, blob: vids.filter(v => v.src.startsWith('blob:')).length,
        imgs: imgs.length, imgsBroken: imgs.filter(i => !(i.complete && i.naturalWidth > 0)).length,
        cards: cardImgs.length, cardsData: cardImgs.filter(i => i.src.startsWith('data:')).length,
        layers: slides.map((s, i) => s.querySelector('.vp-layer') ? [i, s.querySelector('.vp-layer').dataset.vp] : null).filter(Boolean) }; }""")
    check(not external, f"외부 요청 0건 {external[:2]}")
    check(info["videos"] > 0 and info["blob"] == info["videos"], f"영상 {info['videos']}개 모두 blob 으로 풀림({info['blob']})")
    check(info["imgs"] > 0 and info["imgsBroken"] == 0, f"그림 {info['imgs']}개 중 깨진 것 {info['imgsBroken']}개(숨겨진 카드 이미지 포함)")
    check(info["cards"] >= 2 and info["cardsData"] == info["cards"], f"카드 이미지 {info['cards']}개 모두 파일 안(data 주소)")
    check(len(info["layers"]) == 2, f"겹침 층이 있는 영상 장 {len(info['layers'])}개(E · C)")
    print(f"   장 수 {info['slides']} · 겹침 층 {info['layers']}")
    for idx, key in info["layers"]:
      verify_video(page, args.shots, idx, key.split("-")[2])

    # ⑥ 새로고침 직후 — 영상 장에서 새로 고쳐도 카드가 먼저 뜬다(키를 누르기 전에)
    for idx, key in info["layers"]:
      page.goto(copy.as_uri() + f"#{idx + 1}")
      page.reload()
      page.wait_for_function(WAIT_BLOBS, timeout=120000)
      page.wait_for_timeout(600)
      st = page.evaluate(f"""() => {{ const l = document.querySelector('#deck > .slide:nth-child({idx + 1}) .vp-layer');
        const v = document.querySelector('#deck > .slide:nth-child({idx + 1}) video');
        const c = l.querySelector('.vp-card'); return [!c.hidden, v.paused]; }}""")
      check(st[0] and st[1], f"[{key.split('-')[2]}] 영상 장에서 새로고침해도 카드가 먼저 뜨고 영상은 멈춰 있음")
    check(not errors, f"페이지 오류 0건 {errors[:2]}")
    browser.close()
  if not args.keep_copy:
    shutil.rmtree(work, ignore_errors=True)
  bad = [m for ok, m in results if not ok]
  print(f"\n결과: {len(results) - len(bad)}/{len(results)} 통과" + ("" if not bad else f" · ❌ {len(bad)}건"))
  return 1 if bad else 0


if __name__ == "__main__":
  sys.exit(main())
