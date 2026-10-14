"""위 메뉴 폭별 점검 (DF-109 · 2026-10-14 화면 결정 D84 = 융합안 D) — pytest 밖 · 앱을 띄운 뒤 손으로 돌린다.

    python tests/e2e/gnb_widths.py                 # 점검 계정(로컬 관리자 · scripts/personal/check.ps1 과 같은 계정)
    E2E_EMAIL=... E2E_PASSWORD=... python tests/e2e/gnb_widths.py --shots .playwright-mcp/gnb

폭 열두 곳 + 380 ~ 2000 을 20px 마다(+ 2560) 열어 머리 메뉴의 약속을 본다 — 읽기만(서버에 쓰는 요청 없음):
  ① 숨은 묶음 수 = 「더보기」 숫자(0 이면 숫자 없음)   ② 보이는 탭 + 숨은 탭 = 모든 묶음 · 겹침 없음
  ③ 문서 가로 넘침 0 · 반만 잘린 탭 0 · 더보기 · 아바타가 화면 안   ④ 폭이 넓어지면 보이는 탭 수가 줄지 않는다
  ⑤ 1920 에서 열 묶음 모두   ⑥ 지금 묶음(ML·딥러닝 › 모델 비교)이 1280 · 1440 에서 보인다
  ⑦ 키보드 — 더보기에 초점 → Enter 로 열림 → Esc 로 닫히고 초점이 더보기로 · 아바타 메뉴에 로그아웃 · 내 정보
실패가 하나라도 있으면 끝에 목록을 찍고 종료코드 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("BASE_URL", "http://localhost:8966")
EMAIL = os.environ.get("E2E_EMAIL", "smoke-check@example.com")
PASSWORD = os.environ.get("E2E_PASSWORD", "smoke-check-1234")
WIDTHS = [390, 768, 800, 900, 1024, 1280, 1366, 1440, 1536, 1680, 1920, 2560]
SCAN = list(range(380, 2001, 20)) + [2560]

MEASURE_JS = r"""
() => {
  const tabs = [...document.querySelectorAll('#gnb .gnb-tabs .gnb-item[data-gnb]')];
  const bar = document.querySelector('#gnb .gnb-tabs').getBoundingClientRect();
  const vis = tabs.filter(t => getComputedStyle(t).display !== 'none');
  const more = document.getElementById('gnb-more-tab');
  const user = document.getElementById('gnb-user');
  const mr = more ? more.getBoundingClientRect() : null;
  const ur = user ? user.getBoundingClientRect() : null;
  const count = more ? more.querySelector('.gnb-more-count') : null;
  return {
    vw: window.innerWidth, docW: document.documentElement.scrollWidth,
    all: tabs.map(t => t.dataset.gnb),
    visible: vis.map(t => t.dataset.gnb),
    hidden: tabs.filter(t => getComputedStyle(t).display === 'none').map(t => t.dataset.gnb),
    clipped: vis.filter(t => t.getBoundingClientRect().right > bar.right + 0.5).map(t => t.dataset.gnb),
    icons: vis.length ? getComputedStyle(vis[0].querySelector('i')).display !== 'none' : null,
    moreShown: !!mr && mr.width > 0 && getComputedStyle(more).display !== 'none',
    moreInView: !!mr && mr.left >= 0 && mr.right <= window.innerWidth + 0.5,
    moreCount: count && getComputedStyle(count).display !== 'none' ? count.textContent.trim() : '',
    moreHidden: more ? (more.dataset.hidden || '') : null,
    moreActive: more ? more.classList.contains('active') : null,
    userInView: !!ur && ur.width > 0 && ur.right <= window.innerWidth + 0.5,
    ticker: [...document.querySelectorAll('#market-ticker .ticker-item')].filter(t => t.getBoundingClientRect().width > 0).length,
    syncTitle: (document.getElementById('sync-badge') || {}).title || '',
    oldMoreVisible: (() => { const b = document.getElementById('gnb-more-btn'); return !!b && getComputedStyle(b).display !== 'none'; })(),
    logoutVisible: (() => { const b = document.getElementById('logout-btn'); return !!b && getComputedStyle(b).display !== 'none'; })(),
  };
}
"""


def check(width: int, m: dict, fails: list[str], where: str) -> None:
    tag = f"{where} {width}"
    if sorted(m["visible"] + m["hidden"]) != sorted(m["all"]) or set(m["visible"]) & set(m["hidden"]):
        fails.append(f"{tag} ② 보이는 + 숨은 ≠ 모든 묶음")
    want = str(len(m["hidden"])) if m["hidden"] else ""
    if m["moreCount"] != want:
        fails.append(f"{tag} ① 더보기 숫자 「{m['moreCount']}」 ≠ 숨은 수 {len(m['hidden'])}")
    if m["moreHidden"].split() != m["hidden"]:
        fails.append(f"{tag} ① 더보기 data-hidden {m['moreHidden']!r} ≠ 숨은 {m['hidden']}")
    if m["docW"] > m["vw"]:
        fails.append(f"{tag} ③ 문서 가로 넘침 {m['docW']} > {m['vw']}")
    if m["clipped"]:
        fails.append(f"{tag} ③ 반만 잘린 탭 {m['clipped']}")
    if not (m["moreShown"] and m["moreInView"]):
        fails.append(f"{tag} ③ 더보기가 화면 밖")
    if not m["userInView"]:
        fails.append(f"{tag} ③ 아바타가 화면 밖")
    if m["oldMoreVisible"] or m["logoutVisible"]:
        fails.append(f"{tag} 옛 「⋮」 · 로그아웃 단추가 보인다")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="머리 띠 캡처를 둘 폴더(저장소 안이면 .playwright-mcp/ 아래)")
    ap.add_argument("--json", help="잰 값을 쓸 파일")
    args = ap.parse_args()
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    fails: list[str] = []
    out: dict = {"widths": {}, "scan": {}, "ml": {}, "keys": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        res = ctx.request.post(f"{BASE}/api/auth/login", data={"email": EMAIL, "password": PASSWORD})
        if res.status != 200:
            print(f"로그인 실패 {res.status} — 앱이 켜져 있는지 · 계정(E2E_EMAIL)을 확인하세요")
            return 2
        page = ctx.new_page()
        console: list[str] = []
        page.on("console", lambda msg: console.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
        page.on("pageerror", lambda err: console.append(f"[pageerror] {err}"))

        def open_at(width: int, view: str) -> dict:
            page.set_viewport_size({"width": width, "height": 800})
            page.goto("about:blank")
            page.goto(f"{BASE}/app.html#{view}")
            try:
                page.wait_for_selector("#gnb-more-tab", state="attached", timeout=20000)
            except Exception:
                print(f"더보기 단추가 {width} · #{view} 에서 20초 안에 안 생김 — 콘솔:", *console[-8:], sep="\n  ")
                raise
            try:   # 자료 상태 배지가 채워진 뒤에 잰다(늦게 채워지는 칸 — 폭이 바뀐다) · 못 채워져도 그 상태로 잰다
                page.wait_for_function("() => !(document.querySelector('#q-data-badge span:last-child')||{textContent:''}).textContent.includes('…')", timeout=6000)
            except Exception:
                out.setdefault("badge_wait_timeout", []).append(width)
            page.wait_for_timeout(250)
            return page.evaluate(MEASURE_JS)

        for w in WIDTHS:
            m = open_at(w, "dashboard")
            out["widths"][w] = m
            check(w, m, fails, "대시보드")
            if shots:
                page.screenshot(path=str(shots / f"gnb_{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": 60})
        if len(out["widths"][1920]["visible"]) != len(out["widths"][1920]["all"]):
            fails.append(f"⑤ 1920 에서 숨은 묶음 {out['widths'][1920]['hidden']}")

        # ④ 20px 마다 — 한 페이지에서 창 크기만 바꾼다(ResizeObserver 로 다시 맞춤)
        page.set_viewport_size({"width": SCAN[0], "height": 800})
        page.goto("about:blank")
        page.goto(f"{BASE}/app.html#dashboard")
        page.wait_for_selector("#gnb-more-tab", timeout=15000)
        page.wait_for_timeout(800)
        prev = None
        for w in SCAN:
            page.set_viewport_size({"width": w, "height": 800})
            page.wait_for_timeout(120)
            m = page.evaluate(MEASURE_JS)
            out["scan"][w] = {"visible": len(m["visible"]), "icons": m["icons"], "ticker": m["ticker"], "docW": m["docW"]}
            check(w, m, fails, "훑기")
            if prev is not None and len(m["visible"]) < prev[1]:
                fails.append(f"④ {prev[0]} → {w} 에서 보이는 탭 {prev[1]} → {len(m['visible'])}")
            prev = (w, len(m["visible"]))

        # ⑥ 지금 묶음 바꿔 끼우기
        for w in (1024, 1280, 1440):
            m = open_at(w, "ml-compare")
            out["ml"][w] = m
            check(w, m, fails, "모델 비교")
            if "ml" not in m["visible"]:
                fails.append(f"⑥ {w} 모델 비교를 연 채로 ML·딥러닝 탭이 숨었다")
            if m["moreActive"]:
                fails.append(f"⑥ {w} 지금 묶음이 보이는데 더보기가 칠해졌다")
            if shots:
                page.screenshot(path=str(shots / f"gnb_ml_{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": 60})

        # ⑦ 키보드 · 펼침 목록 · 아바타 메뉴
        open_at(1280, "dashboard")
        page.focus("#gnb-more-tab")
        page.keyboard.press("Enter")
        page.wait_for_timeout(150)
        pop = page.evaluate("""() => { const p = document.getElementById('gnb-more-pop'); return {
          open: !p.hidden, expanded: document.getElementById('gnb-more-tab').getAttribute('aria-expanded'),
          rows: [...p.querySelectorAll('[data-gnb-group]')].map(b => b.dataset.gnbGroup),
          drawer: !!p.querySelector('[data-open-drawer]'), focusIn: p.contains(document.activeElement) }; }""")
        out["keys"]["more"] = pop
        if shots:
            page.screenshot(path=str(shots / "gnb_more_open_1280.png"), clip={"x": 0, "y": 0, "width": 1280, "height": 420})
        hidden_1280 = out["widths"][1280]["hidden"]
        if not pop["open"] or pop["expanded"] != "true" or not pop["focusIn"]:
            fails.append(f"⑦ Enter 로 더보기 목록이 안 열림 {pop}")
        if pop["rows"][: len(hidden_1280)] != hidden_1280:
            fails.append(f"⑦ 목록의 숨은 묶음 {pop['rows']} ≠ 숨은 탭 {hidden_1280}")
        if not pop["drawer"]:
            fails.append("⑦ 목록에 「전체 메뉴 보기」 가 없다")
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        after = page.evaluate("() => ({ open: !document.getElementById('gnb-more-pop').hidden, focus: document.activeElement && document.activeElement.id })")
        out["keys"]["esc"] = after
        if after["open"] or after["focus"] != "gnb-more-tab":
            fails.append(f"⑦ Esc 뒤 {after}")
        page.click("#gnb-user")
        page.wait_for_timeout(150)
        user = page.evaluate("""() => { const p = document.getElementById('gnb-user-pop'); return {
          open: !p.hidden, head: (p.querySelector('.gnb-pop-head') || {}).textContent || '',
          items: [...p.querySelectorAll('.gnb-pop-item')].map(b => b.textContent.trim()) }; }""")
        out["keys"]["user"] = user
        if shots:
            page.screenshot(path=str(shots / "gnb_user_open_1280.png"), clip={"x": 880, "y": 0, "width": 400, "height": 240})
        if not user["open"] or "로그아웃" not in user["items"] or not any("내 정보" in t for t in user["items"]):
            fails.append(f"⑦ 아바타 메뉴 {user}")
        page.mouse.click(400, 500)   # 바깥 누름 → 닫힘
        page.wait_for_timeout(100)
        if page.evaluate("() => !document.getElementById('gnb-user-pop').hidden"):
            fails.append("⑦ 바깥을 눌러도 아바타 메뉴가 닫히지 않음")
        browser.close()

    print("폭  보이는 탭  숨은 수  더보기  아이콘  시세  넘침")
    for w, m in out["widths"].items():
        print(f"{w:>4}  {len(m['visible']):>2}  {len(m['hidden']):>2}  「{m['moreCount'] or '-'}」  {'있음' if m['icons'] else '없음'}  {m['ticker']}  {m['docW'] - m['vw']}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if fails:
        print(f"\n실패 {len(fails)}")
        for f in fails:
            print(" -", f)
        return 1
    print(f"\n모두 통과 — 폭 {len(WIDTHS)} · 훑기 {len(SCAN)} · 모델 비교 3 · 키보드 · 아바타")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
