"""발표 그림 초안 굳히기 — Mermaid 원문(.mmd)을 SVG 로 (2026-10-19).

그림은 두 단계다 — ① 이 도구로 그리는 간단한 초안(Mermaid) ② 손으로 쓴 완성 그림(어두운 카드 SVG · `svg_check.py --png` 로 구운 PNG ·
발표 자료가 <img src="그림/…-완성.png"> 로 부른다). 초안은 docs/발표/준비/2026-10-19-발표그림-완성/초안-mermaid/ 에 두고,
이 PC 의 브라우저에서 한 번 그려 같은 폴더에 .svg 로 남긴다(발표 PC 는 인터넷 없이도 그림을 본다).
글자는 SVG 글자로 그린다(htmlLabels 끔) — <img> 로 불러도 글자가 보이게. 글꼴은 발표 PC(Windows)에 있는 맑은 고딕.

  python tools/deck/render_mermaid.py                     # 폴더의 .mmd 모두
  python tools/deck/render_mermaid.py 01-시스템구성.mmd    # 하나만
  python tools/deck/render_mermaid.py --png               # 눈으로 볼 미리 보기 PNG 도(.playwright-mcp/deck/)
Mermaid 는 cdn.jsdelivr.net 의 판 고정(개념 학습 화면과 같은 12.0.0)으로 받는다 — 그릴 때만 인터넷이 필요하다.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import sys
from pathlib import Path
from xml.dom import minidom

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "docs" / "발표" / "준비" / "2026-10-19-발표그림-완성" / "초안-mermaid"
PREVIEW = ROOT / ".playwright-mcp" / "deck"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@12.0.0/dist/mermaid.min.js"
FONT = "Malgun Gothic, 'Noto Sans KR', sans-serif"
CONFIG = {
  # 글자를 SVG 글자로 — Mermaid 12 는 맨 위 htmlLabels 를 읽는다(flowchart 안의 것만 두면 HTML 글자 <br> 이 남아 <img> 로 깨진다)
  "startOnLoad": False, "securityLevel": "strict", "theme": "base", "htmlLabels": False,
  # wrappingWidth — 기본 200px 이면 「공공데이터포 / 털」 처럼 낱말 중간에서 끊긴다 → 넓혀서 원문의 <br/> 에서만 줄을 바꾼다
  "flowchart": {"htmlLabels": False, "curve": "basis", "nodeSpacing": 34, "rankSpacing": 54, "padding": 14, "wrappingWidth": 460},
  "themeVariables": {
    "fontFamily": FONT, "fontSize": "20px",
    "primaryColor": "#eef2ff", "primaryBorderColor": "#4f46e5", "primaryTextColor": "#0f172a",
    "lineColor": "#64748b", "clusterBkg": "#ffffff", "clusterBorder": "#cbd5e1", "edgeLabelBackground": "#ffffff",
    "titleColor": "#334155",
  },
}


async def render(paths: list[Path], png: bool) -> int:
  from playwright.async_api import async_playwright
  bad = 0
  async with async_playwright() as p:
    b = await p.chromium.launch()
    page = await b.new_page(viewport={"width": 1920, "height": 1080})
    await page.set_content(f"<html><head><meta charset='utf-8'></head><body style='margin:0;background:#fff'>"
                           f"<div id='out'></div></body></html>")
    await page.add_script_tag(url=MERMAID)
    await page.evaluate("cfg => mermaid.initialize(cfg)", CONFIG)
    for i, src_path in enumerate(paths):
      src = src_path.read_text(encoding="utf-8")
      try:
        svg = await page.evaluate("async ([id, src]) => (await mermaid.render(id, src)).svg", [f"g{i}", src])
      except Exception as e:  # noqa: BLE001
        print(f"실패 {src_path.name}: {str(e)[:200]}")
        bad += 1
        continue
      try:   # <img> 로 부르는 SVG 는 XML 로 읽힌다 — 깨진 그림을 남기지 않는다
        minidom.parseString(svg.encode("utf-8"))
      except Exception as e:  # noqa: BLE001
        print(f"실패 {src_path.name}: XML 이 아님 — {str(e)[:120]}")
        bad += 1
        continue
      out = src_path.with_suffix(".svg")
      out.write_text(svg, encoding="utf-8")
      print(f"씀 {out.relative_to(ROOT)} · {len(svg):,} 글자")
      if png:
        PREVIEW.mkdir(parents=True, exist_ok=True)
        b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")   # 발표 자료가 <img> 로 부르는 것과 같은 길로 본다
        await page.set_content(f"<html><body style='margin:0;background:#fff'><img id='g' src='data:image/svg+xml;base64,{b64}'"
                               " style='width:1680px'></body></html>")
        await page.wait_for_timeout(300)
        await page.locator("#g").screenshot(path=str(PREVIEW / (src_path.stem + ".png")))
    await b.close()
  return bad


def main() -> int:
  ap = argparse.ArgumentParser(description="발표 자료 Mermaid 그림을 SVG 로 굳힌다")
  ap.add_argument("names", nargs="*", help="그림 원문 파일 이름(없으면 폴더 모두)")
  ap.add_argument("--png", action="store_true", help="미리 보기 PNG 도 남김(.playwright-mcp/deck/)")
  a = ap.parse_args()
  paths = [SRC_DIR / n for n in a.names] if a.names else sorted(SRC_DIR.glob("*.mmd"))
  missing = [p.name for p in paths if not p.exists()]
  if missing:
    print("없는 파일:", missing)
    return 2
  return 1 if asyncio.run(render(paths, a.png)) else 0


if __name__ == "__main__":
  sys.exit(main())
