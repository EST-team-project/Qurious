"""위 메뉴 · 왼쪽 「전체 메뉴」 트리 폭별 점검 (2026-10-18 메뉴 개편 D129 안 가 · 사용자 S124) — pytest 밖 · 앱을 띄운 뒤 손으로 돌린다.

    python tests/e2e/gnb_widths.py                 # 점검 계정(로컬 관리자 · scripts/personal/check.ps1 과 같은 계정)
    E2E_EMAIL=... E2E_PASSWORD=... python tests/e2e/gnb_widths.py --shots .playwright-mcp/gnb

폭 열두 곳 + 380 ~ 2000 을 20px 마다(+ 2560) 열어 메뉴의 약속을 본다 — 읽기만(서버에 쓰는 요청 없음 · 증권사를 부르는 대시보드 대신
AI 상담 화면에서 잰다):
  ① 위 탭은 여섯 전부 아니면 0(반만 보이는 탭 줄이 없다) · 잘린 탭 0   ② 문서 가로 넘침 0 · 아바타가 화면 안
  ③ 폭이 넓어지면 보이는 탭 수가 줄지 않는다   ④ 1280 이상은 탭 여섯 + 아이콘 + 로고 부제
  ⑤ 메뉴는 늘 닿는다 — 768 아래는 ☰ · 그 위는 왼쪽 트리(240) · 트리 묶음 13(묶음이 늘면 이 숫자도)
  ⑥ 지금 묶음(ML·딥러닝 › 모델 비교)이 트리에서 혼자 펼쳐지고 aria-current · 위 탭은 아무것도 칠하지 않음(여섯 밖 묶음)
  ⑦ 키보드 — 390 에서 ☰ 에 초점 → Enter 로 트리 열림(aria-expanded · 초점은 트리 안) → Esc 로 닫히고 초점이 ☰ 로 ·
     어두운 막 누름으로 닫힘 · 아바타 메뉴에 로그아웃 · 내 정보 · 바깥 누름으로 닫힘
옛 「더보기」 · 오른쪽 서랍 · 「⋮」 가 다시 생기면 실패. 실패가 하나라도 있으면 끝에 목록을 찍고 종료코드 1.
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
VIEW = "agent-chat"
TREE_GROUPS = 13

MEASURE_JS = r"""
() => {
  const tabs = [...document.querySelectorAll('#gnb .gnb-tabs .gnb-item[data-gnb]')];
  const bar = document.querySelector('#gnb .gnb-tabs').getBoundingClientRect();
  const vis = tabs.filter(t => getComputedStyle(t).display !== 'none' && t.getBoundingClientRect().width > 0);
  const lnb = document.getElementById('lnb');
  const ham = document.getElementById('hamburger-btn');
  const user = document.getElementById('gnb-user');
  const ur = user ? user.getBoundingClientRect() : null;
  const tag = document.querySelector('.gnb-logo-text span[data-brand="tagline"]');
  const groups = [...document.querySelectorAll('#lnb-nav details.lnb-group')];
  const icon = vis.length ? vis[0].querySelector('i, svg') : null;
  return {
    vw: window.innerWidth, docW: document.documentElement.scrollWidth,
    all: tabs.map(t => t.dataset.gnb), visible: vis.map(t => t.dataset.gnb),
    clipped: vis.filter(t => t.getBoundingClientRect().right > bar.right + 0.5).map(t => t.dataset.gnb),
    icons: icon ? getComputedStyle(icon).display !== 'none' : null,
    tagline: !!tag && getComputedStyle(tag).display !== 'none',
    lnbW: getComputedStyle(lnb).display !== 'none' ? Math.round(lnb.getBoundingClientRect().width) : 0,
    ham: !!ham && getComputedStyle(ham).display !== 'none',
    groups: groups.length, open: groups.filter(g => g.open).map(g => g.dataset.lnbGroup),
    cur: ((document.querySelector('#lnb-nav [aria-current="page"]') || {}).dataset || {}).view || '',
    activeTab: ((tabs.find(t => t.classList.contains('active')) || {}).dataset || {}).gnb || '',
    userInView: !!ur && ur.width > 0 && ur.right <= window.innerWidth + 0.5,
    old: ['gnb-more-tab', 'gnb-offcanvas', 'gnb-more-btn'].filter(id => document.getElementById(id)),
    logoutVisible: (() => { const b = document.getElementById('logout-btn'); return !!b && getComputedStyle(b).display !== 'none'; })(),
  };
}
"""

STATE_JS = r"""
() => ({
  open: document.getElementById('lnb').classList.contains('mobile-open'),
  expanded: document.getElementById('hamburger-btn').getAttribute('aria-expanded'),
  backdrop: getComputedStyle(document.getElementById('lnb-backdrop')).display,
  focusInTree: document.getElementById('lnb').contains(document.activeElement),
  focus: document.activeElement && document.activeElement.id,
})
"""


def check(width: int, m: dict, fails: list[str], where: str) -> None:
    tag = f"{where} {width}"
    if len(m["visible"]) not in (0, len(m["all"])):
        fails.append(f"{tag} ① 탭이 일부만 보인다 {m['visible']}")
    if m["clipped"]:
        fails.append(f"{tag} ① 반만 잘린 탭 {m['clipped']}")
    if m["docW"] > m["vw"]:
        fails.append(f"{tag} ② 문서 가로 넘침 {m['docW']} > {m['vw']}")
    if not m["userInView"]:
        fails.append(f"{tag} ② 아바타가 화면 밖")
    if m["vw"] <= 768 and not m["ham"]:
        fails.append(f"{tag} ⑤ 768 아래인데 ☰ 가 없다")
    if m["vw"] > 768 and m["lnbW"] < 200:
        fails.append(f"{tag} ⑤ 왼쪽 트리가 안 보인다(너비 {m['lnbW']})")
    if m["groups"] != TREE_GROUPS:
        fails.append(f"{tag} ⑤ 트리 묶음 {m['groups']} ≠ {TREE_GROUPS}")
    if m["old"] or m["logoutVisible"]:
        fails.append(f"{tag} 옛 더보기 · 서랍 · ⋮ · 로그아웃 단추가 있다 {m['old']}")
    if m["vw"] >= 1280 and (len(m["visible"]) != len(m["all"]) or not m["icons"] or not m["tagline"]):
        fails.append(f"{tag} ④ 1280 이상인데 탭 {len(m['visible'])} · 아이콘 {m['icons']} · 부제 {m['tagline']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="머리 · 왼쪽 캡처를 둘 폴더(저장소 안이면 .playwright-mcp/ 아래)")
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
                page.wait_for_selector("#lnb-nav details.lnb-group", state="attached", timeout=20000)
            except Exception:
                print(f"트리가 {width} · #{view} 에서 20초 안에 안 생김 — 콘솔:", *console[-8:], sep="\n  ")
                raise
            try:   # 자료 상태 배지가 채워진 뒤에 잰다(늦게 채워지는 칸 — 폭이 바뀐다) · 못 채워져도 그 상태로 잰다
                page.wait_for_function("() => !(document.querySelector('#q-data-badge span:last-child')||{textContent:''}).textContent.includes('…')", timeout=6000)
            except Exception:
                out.setdefault("badge_wait_timeout", []).append(width)
            page.wait_for_timeout(250)
            return page.evaluate(MEASURE_JS)

        for w in WIDTHS:
            m = open_at(w, VIEW)
            out["widths"][w] = m
            check(w, m, fails, "AI 상담")
            if shots:
                page.screenshot(path=str(shots / f"menu_{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": 420})

        # ③ 20px 마다 — 한 페이지에서 창 크기만 바꾼다(ResizeObserver 로 다시 잼)
        page.set_viewport_size({"width": SCAN[0], "height": 800})
        page.goto("about:blank")
        page.goto(f"{BASE}/app.html#{VIEW}")
        page.wait_for_selector("#lnb-nav details.lnb-group", state="attached", timeout=15000)
        page.wait_for_timeout(800)
        prev = None
        for w in SCAN:
            page.set_viewport_size({"width": w, "height": 800})
            page.wait_for_timeout(120)
            m = page.evaluate(MEASURE_JS)
            out["scan"][w] = {"visible": len(m["visible"]), "icons": m["icons"], "tagline": m["tagline"], "docW": m["docW"], "lnbW": m["lnbW"]}
            check(w, m, fails, "훑기")
            if prev is not None and len(m["visible"]) < prev[1]:
                fails.append(f"③ {prev[0]} → {w} 에서 보이는 탭 {prev[1]} → {len(m['visible'])}")
            prev = (w, len(m["visible"]))

        # ⑥ 지금 묶음이 위 탭 여섯 밖일 때 — 트리에서 혼자 펼쳐지고 지금 표시
        for w in (1024, 1280, 1440):
            m = open_at(w, "ml-compare")
            out["ml"][w] = m
            check(w, m, fails, "모델 비교")
            if m["open"] != ["ml"] or m["cur"] != "ml-compare":
                fails.append(f"⑥ {w} 트리 펼침 {m['open']} · 지금 {m['cur']!r}")
            if m["activeTab"]:
                fails.append(f"⑥ {w} 여섯 밖 묶음인데 위 탭 {m['activeTab']!r} 이 칠해졌다")

        # ⑦ 키보드 — 좁은 화면 ☰ 트리
        open_at(390, VIEW)
        page.focus("#hamburger-btn")
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)
        opened = page.evaluate(STATE_JS)
        out["keys"]["ham_open"] = opened
        if shots:
            page.screenshot(path=str(shots / "menu_390_open.png"))
        if not opened["open"] or opened["expanded"] != "true" or opened["backdrop"] != "block" or not opened["focusInTree"]:
            fails.append(f"⑦ Enter 로 ☰ 트리가 안 열림 {opened}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        esc = page.evaluate(STATE_JS)
        out["keys"]["ham_esc"] = esc
        if esc["open"] or esc["expanded"] != "false" or esc["focus"] != "hamburger-btn":
            fails.append(f"⑦ Esc 뒤 {esc}")
        page.click("#hamburger-btn")
        page.wait_for_timeout(200)
        page.mouse.click(375, 500)   # 트리(300) 밖 어두운 막
        page.wait_for_timeout(150)
        dim = page.evaluate(STATE_JS)
        out["keys"]["ham_backdrop"] = dim
        if dim["open"]:
            fails.append(f"⑦ 어두운 막을 눌러도 ☰ 트리가 닫히지 않음 {dim}")

        # ⑦ 아바타 메뉴
        open_at(1280, VIEW)
        page.click("#gnb-user")
        page.wait_for_timeout(150)
        user = page.evaluate("""() => { const p = document.getElementById('gnb-user-pop'); return {
          open: !p.hidden, head: (p.querySelector('.gnb-pop-head') || {}).textContent || '',
          items: [...p.querySelectorAll('.gnb-pop-item')].map(b => b.textContent.trim()) }; }""")
        out["keys"]["user"] = user
        if not user["open"] or "로그아웃" not in user["items"] or not any("내 정보" in t for t in user["items"]):
            fails.append(f"⑦ 아바타 메뉴 {user}")
        page.mouse.click(700, 500)   # 바깥 누름 → 닫힘
        page.wait_for_timeout(100)
        if page.evaluate("() => !document.getElementById('gnb-user-pop').hidden"):
            fails.append("⑦ 바깥을 눌러도 아바타 메뉴가 닫히지 않음")
        browser.close()

    print("폭    탭  아이콘  부제  트리  ☰   넘침")
    for w, m in out["widths"].items():
        print(f"{w:>4}  {len(m['visible']):>2}  {'있음' if m['icons'] else '없음':<4}  {'있음' if m['tagline'] else '없음':<4}  {m['lnbW']:>3}  {'예' if m['ham'] else '-':<2}  {m['docW'] - m['vw']}")
    folds = [w for w in SCAN if out["scan"][w]["visible"]]
    print(f"탭 여섯이 처음 보이는 폭(20px 단위): {folds[0] if folds else '없음'}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if fails:
        print(f"\n실패 {len(fails)}")
        for f in fails:
            print(" -", f)
        return 1
    print(f"\n모두 통과 — 폭 {len(WIDTHS)} · 훑기 {len(SCAN)} · 모델 비교 3 · ☰ 키보드 · 아바타")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
