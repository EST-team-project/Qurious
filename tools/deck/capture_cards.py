"""이동원 슬라이드 10 · 11장의 그림을 카드 PNG 로 캡처한다 — 통합 덱 영상 장의 「카드(멈추고 가운데에 뜨는 그림)」 재료.

왜: 영상 시연 중 멈춰서 보이는 카드는 슬라이드의 현재 그림과 같아야 한다(2026-11-11 30분 발표 재구성 설계 4.2절).
    손으로 캡처하면 슬라이드가 바뀔 때 옛 그림이 남는다 — 이 스크립트로 다시 만들고, --check 로 옛것인지 확인한다.
    (옛 `3차-일지-구조도.png` 는 44행 · 5칸의 낡은 그림이라 쓰지 않는다.)

쓰는 법(저장소 뿌리에서):
  python -I tools/deck/capture_cards.py            # 이동원/그림/카드-신호기록.png · 카드-일지구조.png 를 다시 만든다
  python -I tools/deck/capture_cards.py --check    # 쓰지 않고 PNG 가 슬라이드 HTML 보다 오래됐는지만 본다(오래됐으면 종료 코드 1)

카드: 카드-신호기록.png = 슬라이드 10장 본문(그림 + 쉬운 말 상자) · 카드-일지구조.png = 슬라이드 11장의 구조 그림(SVG).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
RETRO = ROOT / "docs" / "phase-3" / "06-retrospective"
SRC = RETRO / "이동원" / "발표자료.html"
OUT_DIR = RETRO / "이동원" / "그림"

# (파일 이름, 슬라이드 id, 그 안의 요소 선택자)
CARDS = [
  ("카드-신호기록.png", "s10", ".body"),
  ("카드-일지구조.png", "s11", ".chart svg"),
]
MIN_WIDTH = 1800          # 2배 해상도 기준 — 이보다 좁으면 잘못 캡처한 것


def capture_cards(src_html: Path = SRC, out_dir: Path = OUT_DIR) -> list[Path]:
  out_dir.mkdir(parents=True, exist_ok=True)
  made: list[Path] = []
  with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
    page.goto(src_html.resolve().as_uri())
    page.wait_for_timeout(800)
    page.evaluate("() => document.querySelectorAll('section.slide').forEach(s => { s.hidden = false; })")   # 숨긴 장을 모두 연다
    for name, sid, selector in CARDS:
      el = page.locator(f'section.slide[aria-labelledby="{sid}"] {selector}').first
      el.evaluate("e => { e.style.background = '#fff'; e.style.flex = 'none'; e.style.height = 'auto'; }")   # SVG 는 투명이라 흰 바탕을 깔고, 본문은 내용 높이로 줄여 아래 빈 공간을 없앤다
      dest = out_dir / name
      el.screenshot(path=str(dest))
      made.append(dest)
    browser.close()
  for dest in made:
    w = _png_width(dest)
    if w < MIN_WIDTH:
      raise SystemExit(f"멈춤: {dest.name} 가로 {w}px — {MIN_WIDTH}px 미만, 요소를 잘못 잡았다")
  return made


def _png_width(path: Path) -> int:
  head = path.read_bytes()[:24]
  return int.from_bytes(head[16:20], "big")


def check() -> int:
  stale = [name for name, _, _ in CARDS if not (OUT_DIR / name).exists() or (OUT_DIR / name).stat().st_mtime < SRC.stat().st_mtime]
  for name in stale:
    print(f"❌ {name} — 슬라이드 HTML 보다 오래됐거나 없다 → python -I tools/deck/capture_cards.py")
  if not stale:
    print("✅ 카드 PNG 가 슬라이드 HTML 보다 새롭다")
  return 1 if stale else 0


def main() -> int:
  ap = argparse.ArgumentParser(description="이동원 슬라이드 10 · 11장 그림 → 카드 PNG")
  ap.add_argument("--check", action="store_true", help="쓰지 않고 오래됐는지만 본다")
  args = ap.parse_args()
  if args.check:
    return check()
  for p in capture_cards():
    print(f"썼습니다 {p.relative_to(ROOT).as_posix()} · {p.stat().st_size / 1024:.0f} KB · 가로 {_png_width(p)}px")
  return 0


if __name__ == "__main__":
  sys.exit(main())
