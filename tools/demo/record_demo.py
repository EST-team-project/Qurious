"""시연 영상 녹화기 — 장면 파일(YAML) 하나로 영상 · 자막 · 장 파일을 만든다.

쓰는 법 (앱을 켠 뒤 · 저장소 뿌리에서)
  python tools/demo/record_demo.py docs/common/06-retrospective/videos/장면/V01-성향진단-자산배분.yaml
  python tools/demo/record_demo.py <장면.yaml> --no-video        # 영상 없이 단계만 밟아 보기(누를 곳 확인)
  python tools/demo/record_demo.py --inventory agent-chat,robo-portfolio   # 화면마다 누를 곳 목록

나오는 것 (tools/demo/out/ · git 에 넣지 않는다 — 보관은 HF 비공개 데이터셋)
  <이름>.webm · <이름>.ko.vtt(자막) · <이름>.chapters.vtt(장) · <이름>.ch<n>.jpg(장마다 제목 카드 그림)
  · <이름>.json(단계별 시각 · go 단계의 화면 키 · 시작 화면 · 줄인 기다림 · 콘솔 오류 수)
  → 앱의 사용법 창에서 보려면 tools/demo/help_videos.py build (영상 표를 만들어 data/help/ 로)
  → 저장소 · 발표 자료에서 재생할 mp4 는 tools/demo/export_mp4.py (docs/common/06-retrospective/videos/파일/ 로 · 2026-10-19)

계정: 환경 변수 DEMO_EMAIL · DEMO_PASSWORD (없으면 이 PC 로컬 전용 시연 계정 · --ensure-account 면 없을 때 만든다)

왜 이렇게 만들었나
- Playwright 1.59 Python 의 page.screencast 는 프레임을 800×450 으로 줄이고 동작 제목을 영어(Click …)로 띄운다.
  → 크롬 DevTools 의 Page.startScreencast 를 직접 불러 원본 크기(1920×1080) 프레임을 받고,
    커서 · 자막 · 장 제목은 우리가 화면에 얹는다(한국어 · 앱 글꼴).
- AI 답처럼 오래 기다리는 구간은 녹화를 멈췄다가 이어 붙이고, 영상에 「기다린 n초를 줄였다」 를 밝힌다
  (답을 바꿔치기하지 않는다 — 기능을 속이지 않기).
- 프레임은 디스크에 두고 녹화가 끝난 뒤 인코딩한다 — 실시간 인코딩이 밀리면 영상 길이가 어긋나서.
"""
import re
import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

for _s in (sys.stdout, sys.stderr):
  try:
    _s.reconfigure(encoding="utf-8", errors="replace")
  except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]


def _terms_version() -> str:
  """가입 API 가 검증하는 약관 판 번호 — 화면 문구 파일(public/js/terms.js)에서 읽는다."""
  text = (ROOT / "public" / "js" / "terms.js").read_text(encoding="utf-8")
  return re.search(r'TERMS_VERSION = "([^"]+)"', text).group(1)
OUT_DIR = Path(__file__).resolve().parent / "out"
FPS = 25
VW, VH, DSF = 1280, 720, 1.5          # 화면 폭(CSS px) · 배율 → 프레임 1920×1080
KST = timezone(timedelta(hours=9))
LIMIT_SEC = 180                        # 강사님 「각 3분 내외」
DEFAULT_EMAIL = "demo-video@example.com"   # 이 PC 로컬 DB 전용 시연 계정
DEFAULT_PASSWORD = "Qurious-demo-2026!"
DEFAULT_NAME = "체험 사용자"

OVERLAY_JS = r"""
(() => {
  if (window.__demo) return;
  const FONT = "'Pretendard Variable','Pretendard',-apple-system,'Apple SD Gothic Neo',sans-serif";
  const css = `
#__demo-root{position:fixed;inset:0;pointer-events:none;z-index:2147483647;font-family:${FONT}}
#__demo-cursor{position:absolute;left:0;top:0;width:26px;height:26px;transform:translate(640px,360px);will-change:transform}
#__demo-sub{position:absolute;left:50%;bottom:30px;transform:translateX(-50%);max-width:82%;background:rgba(15,23,42,.88);color:#fff;
  font-size:22px;font-weight:600;line-height:1.45;padding:12px 22px;border-radius:14px;text-align:center;opacity:0;transition:opacity .25s;
  box-shadow:0 6px 24px rgba(0,0,0,.25);word-break:keep-all}
#__demo-chap{position:absolute;inset:0;background:rgba(15,23,42,.78);display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .35s}
#__demo-chap .c{max-width:900px;padding:0 48px;color:#fff;text-align:center;word-break:keep-all}
#__demo-chap .k{display:inline-block;font-size:18px;font-weight:700;letter-spacing:.02em;color:#c7d2fe;background:rgba(99,102,241,.28);
  padding:6px 14px;border-radius:999px;margin-bottom:18px}
#__demo-chap .t{font-size:40px;font-weight:800;line-height:1.3;margin:0 0 14px}
#__demo-chap .d{font-size:22px;font-weight:500;line-height:1.55;color:#e2e8f0}
#__demo-ring{position:absolute;border:3px solid #6366f1;border-radius:12px;box-shadow:0 0 0 6px rgba(99,102,241,.22);opacity:0;transition:opacity .2s}
.__demo-ripple{position:absolute;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;background:rgba(99,102,241,.35);
  animation:__demo-rp .55s ease-out forwards}
@keyframes __demo-rp{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}
#__demo-badge{position:absolute;right:22px;top:76px;background:rgba(15,23,42,.82);color:#fff;font-size:16px;font-weight:600;
  padding:8px 14px;border-radius:10px;opacity:0;transition:opacity .25s}`;
  let root, cur, sub, chap, ring, badge;
  function ensure() {
    if (root && document.body.contains(root)) return;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    root = document.createElement('div'); root.id = '__demo-root';
    root.innerHTML = `<svg id="__demo-cursor" viewBox="0 0 24 24"><path d="M4 2 L4 19 L8.6 14.9 L11.6 21.6 L14.6 20.3 L11.7 13.7 L18 13.4 Z" fill="#fff" stroke="#111827" stroke-width="1.6" stroke-linejoin="round"/></svg>
      <div id="__demo-ring"></div><div id="__demo-sub"></div><div id="__demo-badge"></div>
      <div id="__demo-chap"><div class="c"><div class="k"></div><div class="t"></div><div class="d"></div></div></div>`;
    document.body.appendChild(root);
    cur = root.querySelector('#__demo-cursor'); sub = root.querySelector('#__demo-sub'); chap = root.querySelector('#__demo-chap');
    ring = root.querySelector('#__demo-ring'); badge = root.querySelector('#__demo-badge');
  }
  window.__demo = {
    ensure,
    say(t) { ensure(); if (t) sub.textContent = t; sub.style.opacity = t ? 1 : 0; },
    chapter(k, t, d, on) { ensure(); chap.querySelector('.k').textContent = k || ''; chap.querySelector('.t').textContent = t || '';
      chap.querySelector('.d').textContent = d || ''; chap.style.opacity = on ? 1 : 0; },
    move(x, y, ms) { ensure(); cur.style.transition = `transform ${ms}ms cubic-bezier(.25,.7,.25,1)`; cur.style.transform = `translate(${x}px,${y}px)`; },
    ripple(x, y) { ensure(); const r = document.createElement('div'); r.className = '__demo-ripple'; r.style.left = x + 'px'; r.style.top = y + 'px';
      root.appendChild(r); setTimeout(() => r.remove(), 700); },
    ring(x, y, w, h, on) { ensure(); const p = 6; Object.assign(ring.style, {left: (x - p) + 'px', top: (y - p) + 'px', width: (w + 2 * p) + 'px',
      height: (h + 2 * p) + 'px'}); ring.style.opacity = on ? 1 : 0; },
    badge(t) { ensure(); if (t) badge.textContent = t; badge.style.opacity = t ? 1 : 0; },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensure); else ensure();
})();
"""

INVENTORY_JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && e.offsetParent !== null; };
  const view = document.querySelector('.view.active, section.view:not(.hidden), [id^="view-"]:not(.hidden)');
  const scope = view || document.body;
  const out = [];
  for (const e of scope.querySelectorAll('button, a[href], input, select, textarea, [role=button], [role=tab], [data-action]')) {
    if (!vis(e) || e.closest('#__demo-root, nav, header')) continue;
    const t = (e.innerText || e.value || '').trim().replace(/\s+/g, ' ').slice(0, 28);
    out.push([e.tagName.toLowerCase(), e.id ? '#' + e.id : '', t, e.getAttribute('placeholder') || '', e.getAttribute('name') || '',
      e.type || '', [...e.attributes].filter(a => a.name.startsWith('data-')).map(a => a.name + '=' + a.value).join(' ').slice(0, 50)]);
    if (out.length >= 40) break;
  }
  return {scope: view ? (view.id || view.className) : 'body', items: out};
}
"""


def find_ffmpeg():
  for name in ("ffmpeg", "ffmpeg.exe"):
    p = shutil.which(name)
    if p:
      return p
  base = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")) if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else None
  cands = [base] if base else []
  cands += [Path.home() / "AppData/Local/ms-playwright", Path.home() / ".cache/ms-playwright", Path.home() / "Library/Caches/ms-playwright"]
  for c in cands:
    if c and c.exists():
      for f in sorted(c.glob("ffmpeg-*/ffmpeg*"), reverse=True):
        if f.is_file():
          return str(f)
  raise SystemExit("ffmpeg 를 찾지 못했습니다 — `python -m playwright install ffmpeg` 를 한 번 돌리세요")


def vtt_time(sec):
  ms = int(round(sec * 1000))
  h, ms = divmod(ms, 3_600_000)
  m, ms = divmod(ms, 60_000)
  s, ms = divmod(ms, 1000)
  return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


class Recorder:
  """크롬 스크린캐스트 프레임을 받아 디스크에 두고, 25fps 시간표(프레임 번호 목록)를 쌓는다. 멈춘 동안은 시간표가 자라지 않는다."""

  def __init__(self, cdp, frame_dir, enabled=True):
    self.cdp, self.dir, self.enabled = cdp, frame_dir, enabled
    self.n, self.cur, self.timeline = 0, None, []
    self.paused, self.active, self._last, self._task = False, 0.0, None, None
    self.wall_start = time.perf_counter()

  def _on_frame(self, ev):
    (self.dir / f"{self.n:06d}.jpg").write_bytes(base64.b64decode(ev["data"]))
    self.cur = self.n
    self.n += 1
    asyncio.ensure_future(self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]}))

  async def start(self):
    if not self.enabled:
      return
    self.cdp.on("Page.screencastFrame", self._on_frame)
    await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": int(VW * DSF),
                                                "maxHeight": int(VH * DSF), "everyNthFrame": 1})
    for _ in range(100):           # 첫 프레임을 기다린다(정지 화면이면 한 번만 온다)
      if self.cur is not None:
        break
      await asyncio.sleep(0.05)
    self._last = asyncio.get_running_loop().time()
    self._task = asyncio.ensure_future(self._tick())

  async def _tick(self):
    loop = asyncio.get_running_loop()
    while True:
      now = loop.time()
      if not self.paused:
        self.active += now - self._last
        target = int(self.active * FPS)
        while len(self.timeline) < target and self.cur is not None:
          self.timeline.append(self.cur)
      self._last = now
      await asyncio.sleep(0.01)

  @property
  def t(self):
    return len(self.timeline) / FPS if self.enabled else time.perf_counter() - self.wall_start

  async def stop(self):
    if not self.enabled:
      return
    await asyncio.sleep(0.3)
    self._task.cancel()
    try:
      await self.cdp.send("Page.stopScreencast")
    except Exception:
      pass


def encode(rec, out_path, ffmpeg):
  ow, oh = int(VW * DSF), int(VH * DSF)
  cmd = [ffmpeg, "-loglevel", "error", "-f", "image2pipe", "-c:v", "mjpeg", "-framerate", str(FPS), "-i", "pipe:0", "-y", "-an",
         "-c:v", "vp8", "-qmin", "0", "-qmax", "36", "-crf", "8", "-b:v", "4M", "-deadline", "good", "-cpu-used", "4",
         "-threads", "8", "-vf", f"scale={ow}:{oh}:force_original_aspect_ratio=decrease,pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2:white",
         str(out_path)]
  proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
  last_i, last_b = None, b""
  for i in rec.timeline:
    if i != last_i:
      last_b, last_i = (rec.dir / f"{i:06d}.jpg").read_bytes(), i
    proc.stdin.write(last_b)
  proc.stdin.close()
  if proc.wait() != 0:
    raise SystemExit("인코딩 실패 — 위 ffmpeg 오류를 보세요")


async def login(ctx, base, email, password, ensure):
  r = await ctx.request.post(f"{base}/api/auth/login", data={"email": email, "password": password})
  if r.status != 200 and ensure:
    # 본문은 찍지 않는다(보낸 값이 되돌아올 수 있다) — 상태 코드만
    g = await ctx.request.post(f"{base}/api/auth/register", data={"name": DEFAULT_NAME, "email": email, "password": password,
                                                                 "terms_version": _terms_version(), "agreed": ["service", "privacy", "invest"],
                                                                 "birth_date": "1990-01-01"})
    if g.status not in (200, 201):
      raise SystemExit(f"시연 계정 만들기 실패 {g.status} — 비밀번호 규칙(/api/auth/password-policy)을 확인하세요")
    print("시연 계정을 새로 만들었습니다(이 PC 로컬 DB)")
    r = await ctx.request.post(f"{base}/api/auth/login", data={"email": email, "password": password})
  if r.status != 200:
    raise SystemExit(f"로그인 실패 {r.status} — 앱이 켜져 있는지 · 계정(DEMO_EMAIL)을 확인하세요 (없으면 --ensure-account)")


async def locate(page, target, timeout):
  loc = page.locator(target).first
  await loc.wait_for(state="visible", timeout=timeout * 1000)
  return loc


async def bring_into_view(page, loc):
  box = await loc.bounding_box()
  if not box:
    return box
  # 화면보다 긴 요소(긴 답 등)는 가운데가 아니라 머리부터 보이게 — 가운데로 굴리면 답 문장이 화면 밖으로 나간다
  tall = box["height"] > VH - 180
  move = (not (70 <= box["y"] <= VH - 200)) if tall else (box["y"] < 70 or box["y"] + box["height"] > VH - 90)
  if move:
    await loc.evaluate("(e, b) => e.scrollIntoView({behavior: 'smooth', block: b})", "start" if tall else "center")
    await asyncio.sleep(0.8)
    box = await loc.bounding_box()
  return box


async def point_at(page, loc, ms=650):
  box = await bring_into_view(page, loc)
  x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
  await page.evaluate("([x, y, ms]) => __demo.move(x, y, ms)", [x, y, ms])
  await asyncio.sleep(ms / 1000 + 0.12)
  return box, x, y


async def run_step(page, rec, step, ctx_state):
  if not isinstance(step, dict) or len(step) != 1:
    raise ValueError(f"단계는 한 열쇠짜리 묶음이어야 합니다: {step!r}")
  kind, v = next(iter(step.items()))
  opt = v if isinstance(v, dict) else {}
  target = opt.get("target", v if isinstance(v, str) else None)
  timeout = float(opt.get("timeout", 20))

  if kind == "say":
    text = v if isinstance(v, str) else opt.get("text", "")
    await page.evaluate("t => __demo.say(t)", text)
    ctx_state["say"](text)
    if text:
      await asyncio.sleep(0.35)
      ctx_state["snap"]("say")
  elif kind == "chapter":
    ctx_state["chapter"](opt.get("title", ""))
    await page.evaluate("([k, t, d]) => __demo.chapter(k, t, d, true)", [opt.get("label", ""), opt.get("title", ""), opt.get("text", "")])
    await asyncio.sleep(0.9)
    ctx_state["snap"]("chapter")
    ctx_state["poster"]()                       # 장 제목 카드가 다 떴을 때 — 사용법 창 영상의 첫 그림(poster)
    await asyncio.sleep(max(0.0, float(opt.get("sec", 3.0)) - 0.9))
    await page.evaluate("() => __demo.chapter('', '', '', false)")
    await asyncio.sleep(0.4)
  elif kind == "go":
    view = v if isinstance(v, str) else opt["view"]
    item = page.locator(f'#lnb-nav button[data-view="{view}"]').first   # 왼쪽 「전체 메뉴」 트리 항목(2026-10-18 메뉴 개편 D129)
    if opt.get("menu") and await item.is_visible():
      _, x, y = await point_at(page, item)
      await page.evaluate("([x, y]) => __demo.ripple(x, y)", [x, y])
      await item.click()
    else:
      await page.evaluate("k => { location.hash = k; }", view)
    await asyncio.sleep(float(opt.get("after", 1.5)))
  elif kind in ("click", "hover", "ring"):
    loc = await locate(page, target, timeout)
    box, x, y = await point_at(page, loc)
    await page.evaluate("([x, y, w, h]) => __demo.ring(x, y, w, h, true)", [box["x"], box["y"], box["width"], box["height"]])
    if kind == "click":
      await asyncio.sleep(0.25)
      await page.evaluate("([x, y]) => __demo.ripple(x, y)", [x, y])
      await loc.click()
    elif kind == "hover":
      await loc.hover()
    else:
      await asyncio.sleep(0.4)
      ctx_state["snap"]("ring")
    await asyncio.sleep(float(opt.get("sec", 0.6 if kind != "ring" else 2.0)))
    await page.evaluate("() => __demo.ring(0, 0, 0, 0, false)")
    await asyncio.sleep(float(opt.get("after", 0.4)))
  elif kind == "fill":
    loc = await locate(page, target, timeout)
    _, x, y = await point_at(page, loc)
    await page.evaluate("([x, y]) => __demo.ripple(x, y)", [x, y])
    await loc.click()
    await loc.fill("")
    await loc.press_sequentially(str(opt["text"]), delay=float(opt.get("delay", 45)))
    await asyncio.sleep(float(opt.get("after", 0.5)))
  elif kind == "select":
    loc = await locate(page, target, timeout)
    _, x, y = await point_at(page, loc)
    await page.evaluate("([x, y]) => __demo.ripple(x, y)", [x, y])
    if "label" in opt:
      await loc.select_option(label=str(opt["label"]))
    else:
      await loc.select_option(value=str(opt["value"]))
    await asyncio.sleep(float(opt.get("after", 0.8)))
  elif kind == "key":
    await page.keyboard.press(v if isinstance(v, str) else opt["key"])
    await asyncio.sleep(float(opt.get("after", 0.5)))
  elif kind == "scroll":
    if target:
      loc = await locate(page, target, timeout)
      await loc.evaluate("(e, b) => e.scrollIntoView({behavior: 'smooth', block: b})", opt.get("block", "center"))
    else:
      # 앱의 굴러가는 칸은 창이 아니라 내용 칸(#main-content)이다 — 창을 굴리면 아무 일도 없다(2026-10-18 발표 장면 초안에서 찾음)
      await page.evaluate("y => { const m = document.getElementById('main-content');"
                          " const el = m && m.scrollHeight > m.clientHeight ? m : document.scrollingElement;"
                          " el.scrollBy({top: y, behavior: 'smooth'}); }", int(opt.get("by", 400)))
    await asyncio.sleep(float(opt.get("after", 1.0)))
  elif kind == "pause":
    await asyncio.sleep(float(v))
  elif kind == "wait":
    cut = bool(opt.get("cut"))
    t0 = time.perf_counter()
    if cut:
      rec.paused = True
    try:
      await page.locator(target).first.wait_for(state=opt.get("state", "visible"), timeout=timeout * 1000)
      if opt.get("settle"):                      # 글이 흘러나오는 답 — 글자 수가 멈출 때까지
        await page.wait_for_function("([s, ms]) => { const e = document.querySelector(s); if (!e) return false;"
                                     " const n = e.innerText.length; const w = window.__demoSettle || (window.__demoSettle = {});"
                                     " const now = Date.now(); if (w.n !== n) { w.n = n; w.t = now; return false; } return now - w.t > ms; }",
                                     arg=[opt["settle"], 2500], timeout=timeout * 1000, polling=500)
        await page.evaluate("() => { window.__demoSettle = null; }")
    finally:
      rec.paused = False
    waited = time.perf_counter() - t0
    ctx_state["cuts"].append(round(waited, 1) if cut else 0)
    if cut and waited > 2:
      await page.evaluate("t => __demo.badge(t)", f"⏩ 기다린 {waited:.0f}초를 줄였습니다")
      await asyncio.sleep(2.2)
      await page.evaluate("() => __demo.badge('')")
  elif kind == "js":
    await page.evaluate(v)
    await asyncio.sleep(float(opt.get("after", 0.5)) if isinstance(v, dict) else 0.5)
  else:
    raise ValueError(f"모르는 단계 {kind!r}")


async def record(scene_path, args):
  scene = yaml.safe_load(Path(scene_path).read_text(encoding="utf-8"))
  name = scene["file"]
  OUT_DIR = Path(args.out)                          # 사용법 영상은 tools/demo/out · 발표 영상은 tools/demo/out/present(--out)
  OUT_DIR.mkdir(parents=True, exist_ok=True)
  frame_dir = Path(tempfile.mkdtemp(prefix=f"demo-{name}-"))
  base = args.base.rstrip("/")
  email = os.environ.get("DEMO_EMAIL", DEFAULT_EMAIL)
  password = os.environ.get("DEMO_PASSWORD", DEFAULT_PASSWORD)
  subs, chapters, log, errors = [], [], [], []
  ok, failed_at = True, None

  async with async_playwright() as p:
    browser = await p.chromium.launch(headless=not args.headed)
    ctx = await browser.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=DSF, locale="ko-KR", timezone_id="Asia/Seoul")
    await login(ctx, base, email, password, args.ensure_account)
    page = await ctx.new_page()
    accept = scene.get("dialogs") == "accept"                            # 브라우저 확인 창 — 기본 「취소」 · 장면이 정하면 「확인」
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept() if accept else d.dismiss()))
    page.on("pageerror", lambda e: errors.append(str(e)[:160]))
    page.on("console", lambda m: errors.append(m.text[:160]) if m.type == "error" else None)
    # 실패한 응답은 방식 · 주소(쿼리 뺌) · 상태만 — 본문은 남기지 않는다(보낸 값이 되돌아올 수 있다)
    page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.request.method} {r.url.split('?')[0].replace(base, '')}") if r.status >= 400 else None)
    await page.add_init_script(OVERLAY_JS)
    masks = scene.get("mask") or []                 # 흐리게 — 이 PC 정보처럼 자리는 보이되 값은 안 보여야 할 칸
    hides = scene.get("hide") or []                 # 감추기 — 관리자 · 개발용 표시(기능 완성도 배지 등)처럼 영상에 나올 까닭이 없는 칸
    rules = ([",".join(masks) + "{filter:blur(9px)!important}"] if masks else []) + ([",".join(hides) + "{display:none!important}"] if hides else [])
    if rules:
      rule = "".join(rules)
      await page.add_init_script(f"document.addEventListener('DOMContentLoaded',()=>{{const s=document.createElement('style');s.textContent={json.dumps(rule)};document.head.appendChild(s);}});")
    # 이 계정의 이 브라우저에 남은 투자 성향(#251 · #276 — 성향은 서버가 아니라 브라우저에 계정별로만 저장된다). 여정 영상은
    # 편마다 새 브라우저라 앞 편(V01)의 진단이 남지 않는다 — 장면이 risk_profile 을 적으면 같은 계정 · 같은 브라우저를 이어 쓰는 상태로 넣어 둔다.
    rp = scene.get("risk_profile")
    if rp:
      me = await (await ctx.request.get(f"{base}/api/me")).json()
      u = me.get("user") or {}                       # GET /api/me → {"user": {"clientId": …}} (화면 main.js 와 같은 칸)
      cid = str(u.get("clientId") or "")
      if not cid:
        raise SystemExit("risk_profile — /api/me 에 계정 식별자가 없다")
      key = "robo_risk_profile:v1:" + urllib.parse.quote(cid, safe="-_.!~*'()")   # 화면의 encodeURIComponent 와 같은 꼴
      await page.add_init_script(f"try{{localStorage.setItem({json.dumps(key)},{json.dumps(json.dumps(rp, ensure_ascii=False))});}}catch(e){{}}")
    await page.goto(f"{base}/app.html#{scene.get('start', 'dashboard')}", wait_until="load")
    await asyncio.sleep(float(scene.get("warmup", 3.0)))
    await page.evaluate("() => __demo.ensure()")
    cdp = await ctx.new_cdp_session(page)
    rec = Recorder(cdp, frame_dir, enabled=not args.no_video)

    cur = {"say": None, "say_t": 0.0, "chap": None, "chap_t": 0.0}

    def on_say(text):
      if cur["say"]:
        subs.append((cur["say_t"], rec.t, cur["say"]))
      cur["say"], cur["say_t"] = (text or None), rec.t

    def on_chapter(title):
      if cur["chap"]:
        chapters.append((cur["chap_t"], rec.t, cur["chap"]))
      cur["chap"], cur["chap_t"] = title, rec.t

    shots = []
    posters = []                                 # 장마다 제목 카드 프레임 번호(장 차례 그대로)

    def snap(kind):
      if args.frames and rec.enabled and rec.cur is not None:
        shots.append((len(shots) + 1, kind, rec.cur))

    def poster():
      if rec.enabled and rec.cur is not None:
        posters.append(rec.cur)

    state = {"say": on_say, "chapter": on_chapter, "cuts": [], "snap": snap, "poster": poster}
    await rec.start()
    for i, step in enumerate(scene["steps"], 1):
      t0 = rec.t
      try:
        await run_step(page, rec, step, state)
      except Exception as e:
        ok, failed_at = False, f"{i}번째 단계 {json.dumps(step, ensure_ascii=False)[:120]} — {type(e).__name__}: {str(e).splitlines()[0][:160]}"
        print("멈춤:", failed_at)
        break
      entry = {"i": i, "step": list(step)[0], "t": round(t0, 2), "dur": round(rec.t - t0, 2)}
      if entry["step"] == "go":                  # 화면 키를 기록에 남긴다 — 영상 표(사용법 창의 「그 화면이 나오는 장부터」)가
        g = step["go"]                           # 장면 파일이 나중에 바뀌어도 이 녹화의 시각과 어긋나지 않게
        entry["view"] = g if isinstance(g, str) else g.get("view")
      log.append(entry)
    await asyncio.sleep(float(scene.get("tail", 1.0)))
    on_say(None)
    on_chapter(None)
    await rec.stop()
    await browser.close()

  dur = rec.t
  result = {"scene": str(scene_path), "file": name, "title": scene.get("title", ""), "start": scene.get("start", "dashboard"),
            "ok": ok, "failed_at": failed_at, "duration_sec": round(dur, 2),
            "over_limit": dur > LIMIT_SEC, "cut_sec": round(sum(state["cuts"]), 1), "frames_unique": rec.n,
            "console_errors": len(errors), "console_samples": errors[:5],
            "app_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
            "recorded_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
            # 장면 파일 지문(줄 끝 접음) — export_mp4 가 「녹화 뒤 장면이 바뀐 영상」 을 저장소에 내보내지 않게
            "scene_sha": hashlib.sha256(Path(scene_path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16],
            "steps": log}
  if not args.no_video and rec.timeline:
    encode(rec, OUT_DIR / f"{name}.webm", find_ffmpeg())
    result["webm_bytes"] = (OUT_DIR / f"{name}.webm").stat().st_size
    vtt = ["WEBVTT", ""] + [f"{vtt_time(a)} --> {vtt_time(b)}\n{t}\n" for a, b, t in subs if b - a > 0.2]
    (OUT_DIR / f"{name}.ko.vtt").write_text("\n".join(vtt), encoding="utf-8", newline="\n")
    chv = ["WEBVTT", ""] + [f"{vtt_time(a)} --> {vtt_time(b)}\n{t}\n" for a, b, t in chapters if b - a > 0.2]
    (OUT_DIR / f"{name}.chapters.vtt").write_text("\n".join(chv), encoding="utf-8", newline="\n")
    for old in OUT_DIR.glob(f"{name}.ch*.jpg"):  # 장 수가 줄었을 때 지난 녹화의 그림이 남지 않게
      old.unlink()
    result["posters"] = []
    for k, fi in enumerate(posters, 1):
      shutil.copy(frame_dir / f"{fi:06d}.jpg", OUT_DIR / f"{name}.ch{k}.jpg")
      result["posters"].append(f"{name}.ch{k}.jpg")
  (OUT_DIR / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
  if shots:
    sd = OUT_DIR / f"{name}-frames"
    shutil.rmtree(sd, ignore_errors=True)
    sd.mkdir(parents=True)
    for k, kind, i in shots:
      shutil.copy(frame_dir / f"{i:06d}.jpg", sd / f"{k:02d}-{kind}.jpg")
  shutil.rmtree(frame_dir, ignore_errors=True)
  flag = "✅" if ok and not result["over_limit"] else ("⚠️ 3분 넘음" if ok else "❌")
  print(f"{flag} {name} · {dur:.1f}초 · 줄인 기다림 {result['cut_sec']}초 · 콘솔 오류 {len(errors)} · 단계 {len(log)}/{len(scene['steps'])}")
  return 0 if ok else 1


async def inventory(views, args):
  email = os.environ.get("DEMO_EMAIL", DEFAULT_EMAIL)
  password = os.environ.get("DEMO_PASSWORD", DEFAULT_PASSWORD)
  async with async_playwright() as p:
    browser = await p.chromium.launch()
    ctx = await browser.new_context(viewport={"width": VW, "height": VH}, locale="ko-KR")
    await login(ctx, args.base.rstrip("/"), email, password, args.ensure_account)
    page = await ctx.new_page()
    await page.goto(f"{args.base.rstrip('/')}/app.html#{views[0]}", wait_until="load")
    await asyncio.sleep(2.5)
    for v in views:
      await page.evaluate("k => { location.hash = k; }", v)
      await asyncio.sleep(2.0)
      r = await page.evaluate(INVENTORY_JS)
      print(f"## {v} (범위 {r['scope']})")
      for row in r["items"]:
        print("  " + " | ".join(x for x in row if x))
    await browser.close()


def main():
  ap = argparse.ArgumentParser(description="시연 영상 녹화기 (장면 파일 → WebM · 자막 · 장)")
  ap.add_argument("scenes", nargs="*", help="장면 파일(YAML) — 여럿이면 차례대로")
  ap.add_argument("--base", default=os.environ.get("BASE_URL", "http://localhost:8966"))
  ap.add_argument("--no-video", action="store_true", help="영상 없이 단계만 밟아 본다(누를 곳 확인)")
  ap.add_argument("--headed", action="store_true", help="브라우저 창을 띄운다")
  ap.add_argument("--frames", action="store_true", help="자막 · 장 제목 · 강조 순간의 프레임을 out/<이름>-frames/ 에 남긴다(눈으로 훑기)")
  ap.add_argument("--ensure-account", action="store_true", help="시연 계정이 없으면 만든다(이 PC 로컬 DB)")
  ap.add_argument("--inventory", help="화면 키(쉼표로) — 화면마다 누를 곳 목록")
  ap.add_argument("--out", default=str(OUT_DIR),
                  help="결과 폴더 — 사용법 영상은 기본(tools/demo/out) · 발표 영상은 tools/demo/out/present(사용법 영상 표에 섞이지 않게)")
  args = ap.parse_args()
  if args.inventory:
    asyncio.run(inventory([v.strip() for v in args.inventory.split(",") if v.strip()], args))
    return 0
  if not args.scenes:
    ap.print_help()
    return 2
  rc = 0
  for s in args.scenes:
    rc |= asyncio.run(record(s, args))
  return rc


if __name__ == "__main__":
  sys.exit(main())
