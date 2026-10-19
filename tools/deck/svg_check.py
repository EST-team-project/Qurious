"""손으로 쓴 완성 그림(SVG) 점검 · PNG 굽기 (2026-10-19).

문서 그림 지침 「② 완성 그림」 — SVG 가 원본이고 PNG 는 그것을 브라우저(Pretendard)에서 찍은 것이다.
이 도구는 그림마다 ① 글자가 자기를 감싼 카드(<rect>) 밖으로 넘치는지 재고 ② 원래 크기로 PNG 를 굽는다.

  python tools/deck/svg_check.py docs/img/architecture/qurious-architecture_v2.1.svg          # 점검만
  python tools/deck/svg_check.py docs/img/architecture/qurious-architecture_v2.1.svg --png    # 점검 + 같은 이름 .png
넘친 글자가 하나라도 있으면 목록을 찍고 종료코드 1. 글꼴은 cdn.jsdelivr.net 의 Pretendard(판 고정)를 받아 쓴다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FONT_CSS = "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
# 글자의 시작점을 품은 가장 작은 <rect> 를 그 글자의 카드로 본다 — 카드 오른쪽 끝(안쪽 여백 8px)을 넘으면 넘침
PROBE = """() => {
  const svg = document.querySelector('svg');
  const rects = [...svg.querySelectorAll('rect')].map(r => r.getBBox()).filter(b => b.width < 2600 || b.height < 1400);
  const out = [];
  svg.querySelectorAll('text').forEach(t => {
    const b = t.getBBox();
    const anchor = t.getAttribute('text-anchor') || 'start';
    const x0 = anchor === 'middle' ? b.x + b.width / 2 : anchor === 'end' ? b.x + b.width - 1 : b.x + 1;
    const y0 = b.y + b.height / 2;
    const box = rects.filter(r => x0 >= r.x && x0 <= r.x + r.width && y0 >= r.y && y0 <= r.y + r.height)
                     .sort((a, c) => a.width * a.height - c.width * c.height)[0];
    if (!box) return;
    const over = Math.max(b.x + b.width - (box.x + box.width - 8), (box.x + 8) - b.x);
    if (over > 0.5) out.push({ text: t.textContent.slice(0, 40), over: Math.round(over) });
  });
  return out;
}"""


async def check(path: Path, png: bool) -> int:
  from playwright.async_api import async_playwright
  svg = path.read_text(encoding="utf-8")
  import re
  m = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"', svg)
  w, h = (int(float(m.group(1))), int(float(m.group(2)))) if m else (1920, 1080)
  html = (f"<html><head><meta charset='utf-8'><link rel='stylesheet' href='{FONT_CSS}'>"
          f"<style>html,body{{margin:0;background:#07111f}}</style></head><body>{svg}</body></html>")
  async with async_playwright() as p:
    b = await p.chromium.launch()
    page = await b.new_page(viewport={"width": w, "height": h})
    await page.set_content(html)
    await page.evaluate("document.fonts.ready")
    await page.wait_for_timeout(400)
    over = await page.evaluate(PROBE)
    if png:
      out = path.with_suffix(".png")
      await page.locator("svg").screenshot(path=str(out))
      print(f"구움 {out} · {w} × {h}")
    await b.close()
  for o in over:
    print(f"넘침 {o['over']}px · {o['text']}")
  print(f"{path.name}: 넘친 글자 {len(over)}")
  return 1 if over else 0


def main() -> int:
  ap = argparse.ArgumentParser(description="완성 그림 SVG 점검 · PNG 굽기")
  ap.add_argument("svg", nargs="+")
  ap.add_argument("--png", action="store_true")
  a = ap.parse_args()
  bad = 0
  for s in a.svg:
    bad |= asyncio.run(check(Path(s), a.png))
  return bad


if __name__ == "__main__":
  sys.exit(main())
