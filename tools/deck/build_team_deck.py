"""3차 발표 통합 덱 원본 만들기 — 표지 → 담당자별(구분 장 → 발표 슬라이드 → 시연 영상) 순서로 한 덱에 잇는다(2026-11-09).

왜: 발표 자료가 사람별로 흩어져 있었다(영상 모음 덱 · 이동원 슬라이드 · 오준영 슬라이드). 발표 때는 한 파일을 처음부터 끝까지
    넘겨야 하므로, 각자의 원본은 그대로 두고 이 도구가 읽어 와 **하나의 덱**으로 잇는다. 도구를 다시 돌리면 담당자가 고친
    최신 슬라이드 · 대본 · 장면 파일이 그대로 반영된다(같은 입력이면 같은 결과 — 만든 시각을 넣지 않는다).

장 순서(ORDER 의 사람마다):  표지 → [구분 장 → 발표 슬라이드(<이름>/발표자료.html) → 시연 영상(videos/발표/P-<이름>-*.yaml)] × 4명
  - 슬라이드 파일이 없으면(신장환 · 강민석) 구분 장이 「슬라이드 준비 중 — <이름>」 · 「준비 중 — <이름>」 로 그 자리를 지킨다.
    그 사람 폴더에 발표자료.html 이 생기면 다음 실행부터 자동으로 들어온다.
  - 노트(N 키): 슬라이드 파일의 <aside class="notes"> → 없으면 <이름>/발표대본.md 의 「## N장. 제목 (NN초)」 블록 → 없으면 「대본 없음」.

원본은 고치지 않는다 — 읽기만 한다.
  - 영상 덱 CSS · 넘기기 · 노트 · 전체 화면 스크립트는 2차 덱(docs/phase-2/06-retrospective/발표자료-원본.html)에서 빌려 쓴다.
  - 담당자 슬라이드는 `<section class="slide…">` 블록과 그 `<aside class="notes">` 만 가져온다. 담당자 덱 고유의
    스크립트(넘기기 · notes() · 인쇄)와 `#stage`·nav 같은 틀은 가져오지 않는다 — 영상 덱의 넘기기로 통일.

CSS 가두기(스타일이 섞이지 않게 · 두 방향 모두):
  1) 담당자 덱 CSS → 래퍼 클래스(.d-lee · .d-oh …)를 모든 선택자 앞에 붙인다(`h1,h2{…}` → `.d-lee h1, .d-lee h2{…}`).
     `:root`·`body`(글꼴 · 글자색만)는 래퍼로 옮기고, `#stage`·nav·button·`.notes`·`@page`·`@media print` 같은 담당자 덱
     고유 틀은 버린다. 슬라이드 id(s1 …)는 담당자 키를 앞에 붙여 덱 전체에서 겹치지 않게 한다.
  2) 영상 덱 CSS → 모든 선택자의 마지막 조각(주어)에 `:not(:where(.imp *))` 를 붙인다. 가져온 슬라이드는 `.imp` 래퍼
     안에 있으므로 영상 덱의 `.lead` · `.step` · `.src` · `.row` · `*{margin:0}` 가 새어 들지 않는다. 특이도가 0 이라
     영상 덱 안의 우선순위는 그대로이고, 틀(1920×1080 `.slide`) 규칙은 래퍼 바깥이라 계속 맞는다.
  3) 상속 : 영상 덱의 `html,body{word-break:keep-all …}` 는 래퍼에서 초기값으로 되돌린다(`:where(.imp)`).
  4) `--check` 는 최종 CSS 의 선택자를 훑어 가두지 않은 규칙이 있으면 알린다(빌드도 같은 점검으로 멈춘다).

크기: 담당자 덱은 1280×720 으로 만들어졌다 → `.imp` 래퍼를 1920/1280 = 1.5 배로 키워 1920×1080 틀에 꼭 맞춘다
      (비율이 다른 덱이면 가운데에 놓고 알린다).

쓰는 법(저장소 뿌리에서 — yaml 이 든 녹화용 파이썬으로):
  C:\\workspace\\venvs\\demo\\Scripts\\python.exe tools/deck/build_team_deck.py            # 전체-발표자료-원본.html 을 다시 쓴다
  C:\\workspace\\venvs\\demo\\Scripts\\python.exe tools/deck/build_team_deck.py --check    # 쓰지 않고 장 목록 · 파일 유무 · CSS 점검만
  C:\\workspace\\venvs\\demo\\Scripts\\python.exe tools/deck/build_team_deck.py --out <경로>  # 다른 곳에 쓰기(시험용)
  python tools/deck/bundle_deck.py --src docs/phase-3/06-retrospective/전체-발표자료-원본.html --out docs/phase-3/06-retrospective/전체-발표자료.html   # 한 파일 판
"""
from __future__ import annotations

import argparse
import dataclasses
import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I 로 돌려도 같은 폴더의 video_player 를 읽는다
import video_player  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
RETRO = ROOT / "docs" / "phase-3" / "06-retrospective"
SCENES = RETRO / "videos" / "발표"
FILES = RETRO / "videos" / "파일" / "발표"
LIST_JSON = RETRO / "videos" / "파일" / "목록.json"
OUT = RETRO / "전체-발표자료-원본.html"
BASE = ROOT / "docs" / "phase-2" / "06-retrospective" / "발표자료-원본.html"   # CSS · 넘기기 · 영상 로더를 빌려 온다

ORDER = ["이동원", "신장환", "오준영", "강민석"]
KEYS = {"이동원": "lee", "신장환": "shin", "오준영": "oh", "강민석": "kang"}          # 래퍼 클래스 d-<키> · id 접두어 <키>-
COLORS = {"이동원": "#4f46e5", "신장환": "#b45309", "오준영": "#0f766e", "강민석": "#0369a1"}
ROLES = {"이동원": "데이터 · 신호 근거 · 대사", "신장환": "전략 카드 · 성과 검증", "오준영": "배분 · 리밸런싱 · 실행", "강민석": "LEAN 대사 · 모의투자"}
# 팀 시간 배정이 정해지면 채운다(예: {"이동원": "12분"}). 비어 있으면 구분 장에 「미정」 칸으로 나온다 — 시간 배정은 사용자 결정(전체-발표-초안.md 6절).
TARGET_TIME: dict[str, str] = {}

# 발표 순서 조정(사용자 11-09): 문제 정의 · 시장 조사는 맨 앞(이동원이 자기 파트까지 이어서 발표), 한계는 맨 끝(강민석 발표).
TAIL_SLIDES = {"이동원": 2}            # 이동원 슬라이드의 마지막 N장(한계 · 이어갈 길)을 통합 덱 맨 끝으로 보낸다
TAIL_PRESENTER = "강민석"
TAIL_LABEL = "한계와 이어갈 길"
# 덱에서 뺄 장면(장면 파일은 지우지 않는다). 낡은 일봉 방어 영상은 같은 주제의 슬라이드를 뺐고 2차에서 다뤘다(사용자 조율 11-09).
EXCLUDE_SCENES = {"P-이동원-B-낡은일봉방어",
                  # 11-10 사용자 피드백 4번: 슬라이드 11 · 12장(신호 순위 · 근거 모달)이 글 + 캡처로 설명한 것을 영상 한 편(E)이 대신한다.
                  # A(걸러 보기 · 근거)와 D(지금 값 · 새로고침)도 E 가 합쳐 담으므로 덱에서 뺀다(장면 파일 · 사용법 영상은 그대로 둔다).
                  "P-이동원-A-신호순위", "P-이동원-D-신호순위-지금값"}
# 영상을 슬라이드 사이에 끼운다: {장면 stem: (담당자, 그 담당자 슬라이드 몇 장 뒤)}. 여기에 없는 영상은 담당자 슬라이드가 끝난 뒤에 붙는다.
INLINE_VIDEOS = {"P-이동원-E-신호순위-근거-상세": ("이동원", 9),
                 # 30분 발표(사용자 11-11): 슬라이드 9장(수집 ~ 모의 주문 구조) 바로 뒤에 영상 E → 영상 C 를 차례로 둔다.
                 "P-이동원-C-일지판고정": ("이동원", 9)}
VIDEO_ORDER = ["P-이동원-E-신호순위-근거-상세", "P-이동원-C-일지판고정"]       # 같은 자리에 끼는 영상의 순서

# 30분 발표(사용자 11-11 · 설계 3절): 이동원 슬라이드 일부를 덱에서 뺀다. 원본 `이동원/발표자료.html` 은 그대로 — 내용은 발표에서
# 생략하며 넘긴다. 영상 두 구간(E · C)이 10 ~ 15장을 대신하고, 2 · 5 · 8장은 사용자가 뺀다고 했다. 16 · 17장은 TAIL_SLIDES 대로 맨 끝.
SKIP_SLIDES: dict[str, set[int]] = {"이동원": {2, 5, 8, 10, 11, 12, 13, 14, 15}}
# 빠진 장을 가리키는 문구는 덱 쪽에서만 바꾼다(담당자 로컬 번호 기준 · 바꾼 뒤 fix_numbers 가 덱 번호로 바꿈): {(담당자, 장): [(옛 문구, 새 문구)]}
TEXT_PATCH: dict[tuple[str, int], list[tuple[str, str]]] = {
  ("이동원", 1): [("2 ~ 5장", "3 ~ 4장"), ("8 ~ 15장", "9장 · 영상 2편")],
}
CUES_DIR = SCENES / "큐"                                   # 영상 겹침 층의 큐 파일(<장면 stem>.큐.yaml)

# 영상 슬라이드 옆 칸에 「기준」 줄로 밝힐 말(사용자 11-10 S220: 재녹화하지 않고 며칠자 기준인지만 밝힌다).
VIDEO_BASIS = {"P-이동원-C-일지판고정": "11-11 10:18 기준 영상(행 46). 이후 수집 회차마다 행이 하나씩 늘어납니다"}

STAGE_W, STAGE_H = 1920, 1080          # 영상 덱 틀(.slide) 크기
DEFAULT_SRC_W, DEFAULT_SRC_H = 1280, 720   # 담당자 덱 기본 크기(CSS 에서 못 읽을 때)
# 가변형 덱(clamp · vw 로 크기를 정하고 `#<루트 id> .slide` 로 규칙을 쓰며 보이는 장에만 .active 를 붙이는 형식) 전용 설정
SRC_SIZE_OVERRIDE = {"강민석": (1440, 810)}              # 원본이 정한 stage 최대 폭 1440 · 16:9
SRC_ROOT_ID = {"강민석": "qurious-kms-deck"}            # 이 id 를 선택자 맨 앞에서 걷어 내고, 틀 자신의 규칙은 색 변수만 남긴다
SRC_ACTIVE_CLASS = {"강민석"}                            # 장마다 class="active" 를 붙여 `.slide.active { display:flex }` 가 적용되게 한다
GUARD = ":not(:where(.imp *))"          # 영상 덱 규칙에서 가져온 장(.imp) 안쪽을 빼는 가드 — 특이도 0


def esc(s) -> str:
  return html.escape(str(s), quote=True)


def fmt_dur(sec: int | float | None) -> str:
  """초 → 「11분 50초」 · 「49초」."""
  if sec is None:
    return "—"
  sec = int(round(sec))
  m, s = divmod(sec, 60)
  if not m:
    return f"{s}초"
  return f"{m}분" if not s else f"{m}분 {s}초"


def strip_tags(s: str) -> str:
  s = re.sub(r"<br\s*/?>", " ", s)
  return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


# ─────────────────────────────────────────────────────────────────────────────
# CSS 읽기 · 가두기
# ─────────────────────────────────────────────────────────────────────────────

def _scan_top(text: str):
  """괄호 · 대괄호 · 따옴표 바깥(최상위)에 있는 글자의 (위치, 글자)를 차례로 돌려준다."""
  depth, quote, i = 0, "", 0
  while i < len(text):
    c = text[i]
    if quote:
      if c == "\\":
        i += 1
      elif c == quote:
        quote = ""
    elif c in "\"'":
      quote = c
    elif c in "([":
      depth += 1
    elif c in ")]":
      depth = max(0, depth - 1)
    elif depth == 0:
      yield i, c
    i += 1


def split_top(text: str, seps: str) -> list[str]:
  """최상위의 구분자(seps 의 글자)로만 나눈다 — `:not(a,b)` 안의 쉼표 · `url(data:…;base64,…)` 의 세미콜론은 건드리지 않는다."""
  parts, last = [], 0
  for i, c in _scan_top(text):
    if c in seps:
      parts.append(text[last:i])
      last = i + 1
  parts.append(text[last:])
  return parts


def parse_css(css: str) -> list[tuple[str, str | None]]:
  """CSS 를 최상위 규칙 목록 [(머리, 몸통)] 으로 나눈다. 중괄호 깊이로 읽는다(규칙이 한 줄에 몰려 있어도 된다).
  - 일반 규칙: ('h1,h2', 'margin:0')   - 중첩 at-규칙: ('@media print', '… 안쪽 CSS …')
  - 세미콜론으로 끝난 문장: ('@import …', None)   - 최상위 주석: ('/*', '주석 전문')
  """
  out: list[tuple[str, str | None]] = []
  i, n = 0, len(css)
  while i < n:
    while i < n and css[i].isspace():
      i += 1
    if i >= n:
      break
    if css.startswith("/*", i):
      j = css.find("*/", i + 2)
      j = n if j < 0 else j + 2
      out.append(("/*", css[i:j]))
      i = j
      continue
    j, depth, quote = i, 0, ""
    while j < n:                                   # 머리 — `{` 또는 `;` 가 최상위에 나올 때까지
      c = css[j]
      if quote:
        if c == "\\":
          j += 1
        elif c == quote:
          quote = ""
      elif c in "\"'":
        quote = c
      elif c in "([":
        depth += 1
      elif c in ")]":
        depth = max(0, depth - 1)
      elif depth == 0 and c in "{;":
        break
      j += 1
    prelude = css[i:j].strip()
    if j >= n or css[j] == ";":
      if prelude:
        out.append((prelude, None))
      i = j + 1
      continue
    k, d, quote = j + 1, 1, ""                     # 몸통 — 짝이 맞는 `}` 까지
    while k < n and d:
      c = css[k]
      if quote:
        if c == "\\":
          k += 1
        elif c == quote:
          quote = ""
      elif c in "\"'":
        quote = c
      elif c == "{":
        d += 1
      elif c == "}":
        d -= 1
      k += 1
    out.append((prelude, css[j + 1:k - 1].strip()))
    i = k
  return out


def at_name(prelude: str) -> str:
  m = re.match(r"@(?:-[a-z]+-)?([\w-]+)", prelude, re.I)
  return m.group(1).lower() if m else ""


def last_compound_start(sel: str) -> int:
  """선택자의 마지막 조각(주어) 시작 위치 — 마지막 최상위 결합자(공백 · > + ~) 다음."""
  last = 0
  for i, c in _scan_top(sel):
    if c in " \t\n>+~":
      last = i + 1
  return last


def guard_selector(sel: str) -> str:
  """영상 덱 선택자 하나에 가드를 붙인다 — 마지막 조각의 의사 요소(::after 등) 바로 앞에."""
  sel = sel.strip()
  s0 = last_compound_start(sel)
  comp = sel[s0:]
  if re.match(r"(html|body|:root)(?![\w-])", comp) or comp.startswith(("#", ".deck")):
    return sel                                          # 장 바깥 틀(html · body · #hint · #notes-panel · .deck)
  cut = len(comp)
  for i, c in _scan_top(comp):
    if c == ":" and re.match(r"::|:(?:before|after|first-line|first-letter)(?![\w-])", comp[i:]):
      cut = i
      break
  return sel[:s0] + comp[:cut] + GUARD + comp[cut:]


@dataclass
class CssReport:
  label: str
  kept: int = 0
  dropped: list[str] = field(default_factory=list)
  warnings: list[str] = field(default_factory=list)


def guard_css(css: str, rep: CssReport) -> str:
  """영상 덱 CSS 를 가져온 장(.imp) 안으로 새지 않게 가드를 붙인다. 주석 · 규칙 순서는 그대로."""
  out: list[str] = []
  for prelude, body in parse_css(css):
    if prelude == "/*":
      out.append(body or "")
      continue
    if prelude.startswith("@"):
      if body is None:
        out.append(prelude + ";")
      elif at_name(prelude) in ("media", "supports"):
        out.append(f"{prelude} {{\n{guard_css(body, rep)}\n}}")
      else:
        out.append(f"{prelude} {{ {body} }}")          # @page · @font-face · @keyframes — 선택자가 아니다
      continue
    sels = [guard_selector(s) for s in split_top(prelude, ",") if s.strip()]
    rep.kept += 1
    out.append(f"{', '.join(sels)} {{ {body} }}")
  return "\n".join(out)


# 담당자 덱 고유의 틀 — 영상 덱 넘기기로 통일하므로 가져오지 않는다
_DROP_SUBSTR = re.compile(r"#(?:stage|counter|prev|next|notes|print|announce)(?![\w-])|\.sr-only(?![\w-])|\.notes(?![\w-])|\.shownotes(?![\w-])"
                          r"|\.slide(?:\[hidden\]|:last-child)")
_DROP_ELEM = re.compile(r"(?:^|[\s>+~])(?:nav|button)(?![\w-])")
_TEXT_PROP = re.compile(r"^(?:color|font(?:-[a-z-]+)?|line-height|letter-spacing|word-spacing|word-break|text-[a-z-]+|white-space|-webkit-text-size-adjust)$", re.I)
_DROP_AT = {"page", "charset", "import", "namespace"}


def map_import_selector(sel: str, wrapper: str, idp: str) -> tuple[str, list[str]]:
  """담당자 덱 선택자 하나를 래퍼 안으로. 돌려줌: (종류, 선택자들) — 종류: drop · root · text · plain."""
  s = sel.strip()
  if not s or _DROP_SUBSTR.search(s) or _DROP_ELEM.search(s):
    return "drop", []
  if s == ":root":
    return "root", [wrapper]
  if s in ("html", "body", "html body"):
    return "text", [wrapper]
  if s == "*":
    return "plain", [wrapper, f"{wrapper} *"]
  s = re.sub(r"^(?:html|body)(?![\w-])\s*", "", s)                      # `body a` → `a`
  s = re.sub(r"#([A-Za-z_][\w-]*)", lambda m: "#" + idp + m.group(1), s)   # 슬라이드 id 접두어
  s = re.sub(r'\[aria-labelledby=(["\']?)([^"\'\]]+)\1\]', lambda m: f'[aria-labelledby="{idp}{m.group(2)}"]', s)
  return "plain", [f"{wrapper} {s}"]


def scope_import_css(css: str, wrapper: str, idp: str, rep: CssReport, kf: dict[str, str] | None = None) -> str:
  """담당자 덱 CSS 를 래퍼 안으로 가둔다(위 설명 1)."""
  if kf is None:                                                         # @keyframes 이름은 덱 전체에서 겹치지 않게 접두어를 붙인다
    kf = {m.group(1): f"{wrapper.lstrip('.')}-{m.group(1)}" for m in re.finditer(r"@(?:-webkit-)?keyframes\s+([\w-]+)", css)}
  out: list[str] = []
  for prelude, body in parse_css(css):
    if prelude == "/*":
      continue
    if prelude.startswith("@"):
      name = at_name(prelude)
      if body is None or name in _DROP_AT:
        rep.dropped.append(prelude[:40])
        continue
      if name == "media" and re.search(r"\bprint\b", prelude):
        rep.dropped.append(prelude[:40])                                 # 인쇄 판은 영상 덱의 1920×1080 판이 맡는다
        continue
      if name in ("media", "supports"):
        inner = scope_import_css(body, wrapper, idp, rep, kf)
        if inner:
          out.append(f"{prelude} {{\n{inner}\n}}")
        continue
      if name == "keyframes":
        new = re.sub(r"(@(?:-webkit-)?keyframes\s+)([\w-]+)", lambda m: m.group(1) + kf.get(m.group(2), m.group(2)), prelude)
        out.append(f"{new} {{ {body} }}")
        continue
      rep.warnings.append(f"가두지 못하는 규칙을 그대로 둠: {prelude[:50]}")
      out.append(f"{prelude} {{ {body} }}")
      continue
    plain: list[str] = []
    root = text = False
    for s in split_top(prelude, ","):
      kind, mapped = map_import_selector(s, wrapper, idp)
      if kind == "drop":
        if s.strip():
          rep.dropped.append(s.strip()[:40])
      elif kind == "root":
        root = True
      elif kind == "text":
        text = True
      else:
        plain.extend(mapped)
    decls = body or ""
    for old, new in kf.items():                                          # animation 이름 맞춰 바꾸기
      decls = re.sub(rf"(animation(?:-name)?\s*:[^;]*?)(?<![\w-]){re.escape(old)}(?![\w-])", rf"\1{new}", decls)
    emitted = False
    if root:
      out.append(f"{wrapper} {{ {decls} }}")
      emitted = True
    if text:
      keep = [d.strip() for d in split_top(decls, ";") if d.strip() and _TEXT_PROP.match(d.split(":", 1)[0].strip())]
      if keep:
        out.append(f"{wrapper} {{ {'; '.join(keep)} }}")
        emitted = True
    if plain:
      out.append(f"{', '.join(plain)} {{ {decls} }}")
      emitted = True
    if emitted:
      rep.kept += 1
  return "\n".join(out)


# 통합 덱이 직접 쓰는 틀 규칙 — 이 선택자들로 시작하는 것만 가두지 않아도 된다(감사에서 허용)
_OWN_PREFIXES = (".slide.has-imp", ".imp", ":where(.imp)", ".has-imp", ".vp-layer")
_CHROME = re.compile(r"(?:html|body|:root)(?![\w-])")


def audit_css(css: str, wrappers: list[str]) -> list[str]:
  """최종 CSS 의 선택자 중 가두지 않은 것을 찾는다 — 래퍼로 시작 · 가드 포함 · 장 바깥 틀 · 통합 덱 자체 규칙만 통과."""
  bad: list[str] = []

  def walk(text: str) -> None:
    for prelude, body in parse_css(text):
      if prelude == "/*" or body is None:
        continue
      if prelude.startswith("@"):
        if at_name(prelude) in ("media", "supports"):
          walk(body)
        continue
      for s in split_top(prelude, ","):
        s = s.strip()
        comp = s[last_compound_start(s):]
        ok = (GUARD in s
              or any(s == w or s.startswith((w + " ", w + ".", w + ":")) for w in wrappers)
              or _CHROME.match(comp) or comp.startswith(("#", ".deck"))
              or s.startswith(_OWN_PREFIXES))
        if not ok:
          bad.append(s[:70])

  walk(css)
  return bad


# ─────────────────────────────────────────────────────────────────────────────
# 담당자 슬라이드 읽기
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Slide:
  html: str                 # 가져올 `<section class="slide…">` (id 접두어 · hidden 제거 · notes 제거 뒤)
  title: str                # 제목(h1 · h2 글)
  notes: str                # 노트 HTML(없으면 빈 문자열)
  seconds: int | None       # 대본에 적힌 「(NN초)」
  notes_from: str           # 'html' | 'md' | ''


@dataclass
class Personal:
  name: str
  path: Path
  version: str
  css: str
  src_w: int
  src_h: int
  slides: list[Slide]
  script_path: Path | None = None
  warnings: list[str] = field(default_factory=list)

  @property
  def total_seconds(self) -> int | None:
    secs = [s.seconds for s in self.slides]
    return sum(secs) if secs and all(x is not None for x in secs) else (sum(x for x in secs if x) or None)


def split_sections(body: str) -> list[tuple[str, str]]:
  """최상위 `<section …>…</section>` 를 [(여는 태그, 안쪽 HTML)] 로. 중첩 section 은 안쪽에 그대로 둔다."""
  out, depth, start, open_tag = [], 0, 0, ""
  for m in re.finditer(r"<(/?)section\b([^>]*)>", body):
    if not m.group(1):
      if depth == 0:
        start, open_tag = m.end(), m.group(0)
      depth += 1
    else:
      depth -= 1
      if depth == 0:
        out.append((open_tag, body[start:m.start()]))
      elif depth < 0:
        raise SystemExit("멈춤: </section> 이 여는 태그보다 많다")
  if depth != 0:
    raise SystemExit("멈춤: <section> 이 닫히지 않았다")
  return out


def parse_attrs(tag: str) -> list[tuple[str, str | None]]:
  inner = re.sub(r"^<section\b|>$", "", tag).strip()
  return [(m.group(1), None if m.group(2) is None else m.group(2)[1:-1] if m.group(2)[0] in "\"'" else m.group(2))
          for m in re.finditer(r"""([^\s=]+)(?:=("[^"]*"|'[^']*'|[^\s>]+))?""", inner)]


def read_script_md(path: Path) -> dict[int, tuple[str, int | None, str]]:
  """발표대본.md 의 「## N장. 제목 (NN초)」 블록 → {N: (제목, 초, 대사)}. 대사는 큰따옴표(“ ”) 안쪽, 없으면 블록 전체."""
  text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
  out: dict[int, tuple[str, int | None, str]] = {}
  for m in re.finditer(r"^##\s*(\d+)\s*장\.?\s*(.*?)\s*(?:\((\d+)\s*초\))?\s*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S):
    block = m.group(4).strip()
    q = re.search(r"[“\"](.*?)[”\"]", block, re.S)
    say = (q.group(1) if q else block).strip()
    out[int(m.group(1))] = (m.group(2).strip(), int(m.group(3)) if m.group(3) else None, " ".join(say.split()))
  return out


def read_personal(name: str) -> Personal | None:
  """<이름>/발표자료.html 이 있으면 읽는다. 없으면 None(준비 중 구분 장)."""
  path = RETRO / name / "발표자료.html"
  if not path.is_file():
    return None
  key = KEYS[name]
  raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
  if "<body" not in raw:
    raise SystemExit(f"멈춤: {path} 에 <body> 가 없다")
  head, body = raw[:raw.index("<body")], raw[raw.index("<body"):]
  css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", head, re.S))
  ver = re.search(r'<meta name="doc-version" content="([^"]+)"', head)
  warns: list[str] = []
  root_id = SRC_ROOT_ID.get(name)
  if root_id:
    rid = re.escape(root_id)
    def frame_rule(mm: re.Match) -> str:                               # `#root { … }` — 폭 · 높이 · 배경은 영상 덱 틀이 정하므로 색 변수(--x)만 남긴다
      variables = "".join(re.findall(r"--[\w-]+\s*:[^;]+;", mm.group(2)))
      return f"{mm.group(1)} :root {{ {variables} }}"
    css = re.sub(rf"(^|[{{}}])\s*#{rid}\s*\{{([^}}]*)\}}", frame_rule, css)
    css = re.sub(rf"#{rid}(?![\w-])\s*", "", css)                      # `#root .slide` → `.slide`
  m = re.search(r"(?:^|\})\s*\.slide\s*\{([^}]*)\}", css)
  sw = sh = None
  if m:
    w, h = re.search(r"(?<![\w-])width:\s*(\d+)px", m.group(1)), re.search(r"(?<![\w-])height:\s*(\d+)px", m.group(1))
    sw, sh = (int(w.group(1)) if w else None), (int(h.group(1)) if h else None)
  if name in SRC_SIZE_OVERRIDE:
    sw, sh = SRC_SIZE_OVERRIDE[name]
  elif not (sw and sh):
    sw, sh = DEFAULT_SRC_W, DEFAULT_SRC_H
    warns.append(f"슬라이드 크기를 CSS 에서 못 읽어 {sw}×{sh} 로 가정")
  elif abs(sw / sh - STAGE_W / STAGE_H) > 0.01:
    warns.append(f"슬라이드 비율 {sw}×{sh} 가 16:9 가 아니다 — 가운데에 놓고 남는 곳은 빈칸")
  secs = split_sections(body)
  ids = {i for _, inner in secs for i in re.findall(r'\bid="([^"]+)"', inner)}
  for tag, _ in secs:
    ids.update(v for k, v in parse_attrs(tag) if k == "id" and v)
  script_md = RETRO / name / "발표대본.md"
  md = read_script_md(script_md) if script_md.is_file() else {}

  def rename_ids(text: str) -> str:
    def sub_attr(mm: re.Match) -> str:
      return mm.group(1) + " ".join((key + "-" + t) if t in ids else t for t in mm.group(2).split()) + '"'
    text = re.sub(r'(\bid="|\baria-labelledby="|\baria-describedby="|\baria-controls="|\bfor=")([^"]*)"', sub_attr, text)
    text = re.sub(r'(href="#)([^"]+)"', lambda mm: mm.group(1) + (key + "-" + mm.group(2) if mm.group(2) in ids else mm.group(2)) + '"', text)
    return re.sub(r"url\(#([^)]+)\)", lambda mm: f"url(#{key}-{mm.group(1)})" if mm.group(1) in ids else mm.group(0), text)

  def fix_rel(text: str) -> str:
    """담당자 슬라이드의 상대 이미지 경로(`그림/…`)는 담당자 폴더 기준이라, 통합 덱(한 단계 위)에서 보이도록 폴더 이름을 앞에 붙인다."""
    return re.sub(r'(\bsrc=")(?!https?:|data:|/|#)([^"]+)"', lambda mm: f'{mm.group(1)}{name}/{mm.group(2)}"', text)

  # 강민석 덱처럼 aside.notes 가 아니라 스크립트의 `const notes = ['…', …];` 배열에 대본을 둔 경우 — 장 순서대로 읽는다
  js_notes: list[str] = []
  jm = re.search(r"\bconst\s+notes\s*=\s*\[(.*?)\n\s*\];", body, re.S)
  if jm:
    # 작은따옴표('…') · 큰따옴표("…") 어느 쪽이든 읽는다(강민석 덱이 11-10 17시 PR #635 에서 큰따옴표로 바뀌었다)
    js_notes = [re.sub(r"\\(['\"\\])", r"\1", a or b)     # findall 은 안 맞은 그룹을 None 이 아니라 '' 로 준다
                for a, b in re.findall(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", jm.group(1))]

  slides: list[Slide] = []
  for n, (tag, inner) in enumerate(secs, 1):
    note_m = re.search(r'<aside\b[^>]*class="[^"]*\bnotes\b[^"]*"[^>]*>(.*?)</aside>', inner, re.S)
    notes_html, notes_from, seconds = "", "", None
    if note_m:
      notes_html = note_m.group(1).strip()
      inner = inner[:note_m.start()] + inner[note_m.end():]
      notes_from = "html"
      sm = re.search(r"\((\d+)\s*초\)", strip_tags(notes_html)[:40])
      seconds = int(sm.group(1)) if sm else None
    elif n in md:
      t, sec, say = md[n]
      notes_html = f"<b>{n}장{f' ({sec}초)' if sec else ''}</b> {esc(say)}"
      notes_from, seconds = "md", sec
    elif n <= len(js_notes):
      notes_html = f"<b>{n}장</b> {esc(js_notes[n - 1])}"
      notes_from = "js"
    if "<script" in inner:
      warns.append(f"{n}장 안에 <script> 가 있다 — 영상 덱 넘기기만 쓰므로 동작하지 않는다")
    attrs = []
    for k, v in parse_attrs(tag):
      if k == "hidden":
        continue                                                       # 영상 덱이 장 보임을 정한다
      attrs.append(k if v is None else f'{k}="{esc(v) if k != "class" else v}"')
    if name in SRC_ACTIVE_CLASS:
      attrs = [re.sub(r'^class="([^"]*)"$', lambda mm: f'class="{mm.group(1)} active"' if "active" not in mm.group(1).split() else mm.group(0), a) for a in attrs]
    open_tag = rename_ids("<section " + " ".join(attrs) + ">")
    h = re.search(r"<h[12]\b[^>]*>(.*?)</h[12]>", inner, re.S)
    slides.append(Slide(html=open_tag + fix_rel(rename_ids(inner.rstrip())) + "</section>", title=strip_tags(h.group(1)) if h else f"{n}장",
                        notes=notes_html, seconds=seconds, notes_from=notes_from))
  if md and len(md) != len(secs):
    warns.append(f"발표대본.md 는 {len(md)}장 블록 · 슬라이드는 {len(secs)}장 — 장 수가 다르다")
  if not slides:
    warns.append("<section> 이 하나도 없다")
  return Personal(name=name, path=path, version=ver.group(1) if ver else "?", css=css, src_w=sw, src_h=sh, slides=slides,
                  script_path=script_md if md else None, warnings=warns)


# ─────────────────────────────────────────────────────────────────────────────
# 영상(장면 파일)
# ─────────────────────────────────────────────────────────────────────────────

def load_scenes():
  rows = []
  for p in sorted(SCENES.glob("P-*.yaml")):
    if p.stem in EXCLUDE_SCENES:
      continue
    sc = yaml.safe_load(p.read_text(encoding="utf-8"))
    says = [s["say"] for s in sc.get("steps", []) if isinstance(s, dict) and "say" in s]
    chapters = [s["chapter"] for s in sc.get("steps", []) if isinstance(s, dict) and "chapter" in s]
    rows.append({"stem": p.stem, "title": sc.get("title", p.stem), "owner": sc.get("owner", ""), "says": says, "chapters": chapters})
  rows.sort(key=lambda r: (ORDER.index(r["owner"]) if r["owner"] in ORDER else 99, r["stem"]))
  return rows


def load_durations() -> dict[str, float]:
  """영상 길이(초) — 파일/목록.json(tools/demo/export_mp4.py 가 쓴다)에서. 없으면 빈 사전(길이는 「—」)."""
  try:
    data = json.loads(LIST_JSON.read_text(encoding="utf-8"))
  except (OSError, ValueError):
    return {}
  return {v["stem"]: float(v["duration_sec"]) for v in data.get("videos", []) if v.get("kind") == "발표" and v.get("duration_sec")}


def player_layer(stem: str) -> str:
  """큐 파일(CUES_DIR)과 녹화 기록(FILES/<stem>.events.json)이 둘 다 있으면 겹침 층 HTML, 없으면 빈 문자열(예전 모양 그대로)."""
  cue_path, ev_path = CUES_DIR / f"{stem}.큐.yaml", FILES / f"{stem}.events.json"
  if cue_path.is_file() and not ev_path.is_file():
    raise SystemExit(f"멈춤: 큐 파일 {cue_path.name} 은 있는데 녹화 기록 {ev_path.name} 이 없다 — 영상을 --clean 으로 녹화하고 export_mp4 로 내보내세요")
  if not cue_path.is_file():
    return ""
  events = json.loads(ev_path.read_text(encoding="utf-8"))
  cues = video_player.resolve_cues(video_player.load_cue_file(cue_path), events)   # 기록에 없는 순번이면 ValueError — 조용히 넘기지 않는다
  return video_player.player_markup(stem, cues, video_player.captions(events), video_player.chapter_cards(events),
                                    events["video_sec"], events["vw"], events["vh"])


def video_slide(r) -> str:
  stem, owner = r["stem"], r["owner"]
  has = (FILES / f"{stem}.mp4").exists()
  ch = r["chapters"]
  purpose = (ch[0].get("text") if ch else "") or r["title"]
  tail = (ch[-1].get("text") if ch else "") or ""
  notes = "자막(대사): " + " / ".join(r["says"]) if r["says"] else "자막 없음"
  basis = VIDEO_BASIS.get(stem)
  basis_html = f"<br><br><b>기준</b>{esc(basis)}" if basis else ""
  layer = player_layer(stem)
  # 겹침 층이 있는 영상은 영상만 전체 화면 · 화면 속 화면으로 가지 못하게 한다 — 그러면 자막 · 말풍선이 안 보인다(최종 검토)
  vattr = ' controlslist="nofullscreen noremoteplayback" disablepictureinpicture' if layer else ""
  return f'''<section class="slide" data-title="{esc(owner)} · {esc(stem)}">
  <div class="kicker">{esc(owner)} · {esc(r["title"])}</div>
  <div class="video-wrap" data-video="{esc(stem)}">
    <video controls{vattr} preload="metadata" poster="videos/파일/발표/{esc(stem)}.jpg" src="videos/파일/발표/{esc(stem)}.mp4"></video>
    <div class="missing">영상 파일을 찾지 못했습니다{'' if has else '(아직 내보내지 않았습니다)'}<br>docs/phase-3/06-retrospective/videos/파일/발표/ 를 받은 뒤 다시 열어 주세요</div>
    {layer}
  </div>
  <div class="video-side"><b>목적</b>{esc(purpose)}<br><br><b>마지막 장</b>{esc(tail)}{basis_html}</div>
  <div class="foot"><b>Qurious</b><span class="pg"></span></div>
  <aside class="notes">{esc(notes)}</aside>
</section>'''


# ─────────────────────────────────────────────────────────────────────────────
# 장 만들기
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Frame:
  kind: str            # cover | divider | slide | video
  owner: str
  title: str
  html: str
  note_state: str      # 'html' | 'md' | 'own'(구분 장 · 영상 자막) | ''(대본 없음)
  seconds: int | None = None


def renumber_refs(text: str, m: dict[int, int]) -> str:
  """본문 · 노트의 「N장」 참조(「10 ~ 12장」 · 「8 · 9장」 포함)를 담당자 덱 안의 번호에서 통합 덱 번호로 바꾼다. 모르는 번호는 그대로 둔다."""
  def rep(mm: re.Match) -> str:
    toks = re.split(r"(\s*(?:~|·)\s*)", mm.group(1))
    return "".join(str(m.get(int(t), t)) if t.isdigit() else t for t in toks) + mm.group(2)
  return re.sub(r"((?:\d+\s*(?:~|·)\s*)*\d+)(\s*장)", rep, text)


def fix_numbers(html_: str, gno: int, total: int, m: dict[int, int]) -> str:
  """가져온 슬라이드의 쪽 번호를 덱 전체 번호 하나로 맞춘다 — 풋터의 「3 / 29」 → 「N / 전체」, 눈썹의 「3 · 」 제거, 「N장」 참조 변환."""
  html_ = re.sub(r'(<span class="pg">)\s*\d+\s*/\s*\d+\s*(</span>)', rf"\g<1>{gno} / {total}\g<2>", html_)
  # 강민석 덱 형식: <div class="foot"><span>설명</span><span>04 / 13</span></div> — 마지막 칸의 쪽 번호만 바꾼다
  html_ = re.sub(r'(<div class="foot">(?:(?!</div>).)*?)<span>\s*\d+\s*/\s*\d+\s*</span>(</div>)', rf'\g<1><span class="pg">{gno} / {total}</span>\g<2>', html_, flags=re.S)
  # 오준영 덱 형식: <footer class="footer"><span>설명</span><span>02 / 06</span></footer> — 쪽 번호 칸에 class 가 없다(11-10 사용자 피드백: 「오준영 슬라이드 1, 2, … 로 넘어간다」)
  html_ = re.sub(r'(<footer class="footer">(?:(?!</footer>).)*?)<span>\s*\d+\s*/\s*\d+\s*</span>(</footer>)', rf'\g<1><span class="pg">{gno} / {total}</span>\g<2>', html_, flags=re.S)
  html_ = re.sub(r'(<p class="eyebrow">)\d+ · ', r"\1", html_)
  return renumber_refs(html_, m)


def imported_frame(p: Personal, i: int, sl: Slide, label: str = "", owner: str = "") -> str:
  """담당자 슬라이드 한 장을 1920×1080 틀에 넣는다 — `.imp` 래퍼를 키워(1280→1920 = ×1.5) 꼭 맞춘다.
  label · owner: 맨 끝으로 옮긴 장(한계)에서 발표자 표시를 바꿀 때(예: 「한계와 이어갈 길 · 강민석 발표」)."""
  key = KEYS[p.name]
  scale = min(STAGE_W / p.src_w, STAGE_H / p.src_h)
  dx, dy = (STAGE_W - p.src_w * scale) / 2, (STAGE_H - p.src_h * scale) / 2
  move = f"translate({dx:g}px,{dy:g}px) " if (dx or dy) else ""
  style = f"width:{p.src_w}px;height:{p.src_h}px;transform:{move}scale({scale:g})"
  notes = sl.notes or f"대본 없음 — {p.name}/발표자료.html 에 aside.notes 도, {p.name}/발표대본.md 의 {i}장 블록도 없습니다."
  title = f"{label or p.name} · {sl.title}"
  return f'''<section class="slide has-imp" data-owner="{esc(owner or p.name)}" data-title="{esc(title)}">
  <div class="gnum"><b>{esc(label or p.name)}</b><span class="pg"></span></div>
  <div class="imp d-{key}" style="{style}">
{sl.html}
  </div>
  <aside class="notes">{notes}</aside>
</section>'''


def divider(name: str, no: int, total: int, p: Personal | None, vids: list[dict], dur: dict[str, float], tail_note: str = "") -> str:
  """사람이 바뀌는 곳의 구분 장(HTML). 발표자 노트에 파트 요약이 들어 있다."""
  n_sl = len(p.slides) if p else 0
  sl_sec = (p.total_seconds or 0) if p else 0
  vd = [dur.get(v["stem"]) for v in vids]
  vid_sec = sum(d for d in vd if d)
  total_sec = sl_sec + vid_sec
  if not p and not vids:
    banner = f"준비 중 — {name}"
  elif not p:
    banner = f"슬라이드 준비 중 — {name}"
  else:
    banner = ""

  def label(stem: str) -> str:
    parts = stem.split("-")                       # P-이동원-A-신호순위 → 「A편」
    return f"{parts[2]}편" if len(parts) > 2 else stem

  sl_s = (f"대본 {fmt_dur(sl_sec)}" if sl_sec else "대본 시간 표시 없음") if p else f"{name}/발표자료.html 이 생기면 다시 만들 때 들어옵니다"
  vid_s = " · ".join(f"{label(v['stem'])} {fmt_dur(d)}" for v, d in zip(vids, vd)) if vids else "장면 파일(videos/발표/P-" + name + "-*.yaml)이 생기면 들어옵니다"
  if not total_sec:
    est_s = "슬라이드 · 영상이 들어오면 계산됩니다"
  elif not p:
    est_s = f"영상 {fmt_dur(vid_sec)} · 슬라이드 준비 중"
  else:
    est_s = f"대본 {fmt_dur(sl_sec)} + 영상 {fmt_dur(vid_sec)} · 재 보지 않은 예상"
  tgt = TARGET_TIME.get(name, "")
  cells = [
    ("슬라이드", f"{n_sl}장" if p else "준비 중", sl_s, "" if p else " blank"),
    ("시연 영상", f"{len(vids)}편" if vids else "준비 중", vid_s, "" if vids else " blank"),
    ("예상 시간", fmt_dur(total_sec) if total_sec else "—", est_s, "" if total_sec else " blank"),
    ("목표 시간", tgt or "미정", "팀 시간 배정이 정해지면 채웁니다" if not tgt else "팀 시간 배정", "" if tgt else " blank"),
  ]
  facts = "".join(f'<div class="fact{c}"><div class="k">{k}</div><div class="v">{esc(v)}</div><div class="s">{esc(s)}</div></div>' for k, v, s, c in cells)
  pending = f'<div class="pending">{esc(banner)}</div>' if banner else ""
  bits = [f"슬라이드 {n_sl}장" if p else "슬라이드 없음", f"시연 영상 {len(vids)}편"]
  if total_sec:
    bits.append(f"예상 {fmt_dur(total_sec)}(" + " + ".join(x for x in (f"대본 {fmt_dur(sl_sec)}" if sl_sec else "", f"영상 {fmt_dur(vid_sec)}" if vid_sec else "") if x) + ")")
  bits.append(f"목표 시간 {tgt or '미정'}")
  note = " → ".join(bits[:2]) + " · " + " · ".join(bits[2:]) + (f" · {banner}" if banner else "") + (f" · {tail_note}" if tail_note else "")
  html_ = f'''<section class="slide part person" style="--pc:{COLORS[name]}" data-owner="{esc(name)}" data-title="{esc(name)} 파트 시작">
  <div class="in">
    <div class="no">파트 {no} / {total}</div>
    <h1>{esc(name)}</h1>
    <p>{esc(ROLES[name])}</p>
    {pending}
    <div class="facts">{facts}</div>
  </div>
  <div class="foot"><b>Qurious</b><span class="pg"></span></div>
  <aside class="notes">{esc(note)}</aside>
</section>'''
  return html_


def cover(people: list[dict], n_slides: int | None = None) -> str:
  chips = "".join(f'<span class="chip"><i style="background:{COLORS[o]}"></i>{o} · {ROLES[o]}</span>' for o in ORDER)
  n_sl = n_slides if n_slides is not None else sum(len(x["personal"].slides) for x in people if x["personal"])   # 덱에 실제로 들어간 슬라이드 수
  n_vd = sum(len(x["vids"]) for x in people)
  srcs = " · ".join(f"{x['name']} 발표자료 v{x['personal'].version}" for x in people if x["personal"])
  return f'''<section class="slide cover" data-title="표지">
  <div class="bar"></div>
  <div class="in">
    <div class="logo"><div class="mark"></div><div class="name">Qurious</div></div>
    <p class="one">Qurious 3차 — 나만의 투자 인디케이터</p>
    <p class="two">내 투자 규칙을 지표로 만들고, TradingView · QuantConnect LEAN 으로 다시 검증하고, 증권사 모의계좌까지 이어 줍니다. 신호의 근거와 반대 근거를 함께 보여 주고, 검증한 것과 못 한 것을 구분해서 말씀드립니다.</p>
  </div>
  <div class="team">{chips}</div>
  <div class="date" style="bottom:200px">3차 프로젝트 발표 · 2026.11.12</div>
  <aside class="notes">{" → ".join(ORDER)} 순서로 담당 슬라이드와 시연 영상을 이어서 보여 드립니다. 슬라이드 {n_sl}장 · 시연 영상 {n_vd}편 · 사람이 바뀌는 곳에 구분 장 · 맨 끝에 한계와 이어갈 길({TAIL_PRESENTER} 발표). 팀원 확인용 통합 초안입니다. 이동원 · 오준영 슬라이드는 각자 발표자료.html 에서, 영상은 장면 파일에서 도구가 읽어 옵니다(원본 버전: {esc(srcs)}). 장마다 N 키(발표자 노트)에 대본 또는 자막 전문이 있습니다.</aside>
</section>'''


# 영상 덱 CSS 에 더하는 장 — 구분 장(.part 의 확장). 영상 덱 CSS 와 함께 가드가 붙는다.
EXTRA_VD_CSS = """
/* 사람 구분 장(통합 덱) */
.part.person .in { top: 215px; }
.part.person .no { color: var(--pc); }
.part.person h1 { display: flex; align-items: center; gap: 30px; }
.part.person h1::before { content: ""; width: 20px; height: 92px; border-radius: 10px; background: var(--pc); }
.part.person .pending { display: inline-block; margin-top: 30px; padding: 14px 34px; border: 3px dashed var(--pc); border-radius: 18px; font-size: 40px; font-weight: 800; color: var(--pc); background: #fff; }
.part.person .facts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 26px; margin-top: 52px; }
.part.person .fact { border: 1px solid var(--line); border-radius: 24px; background: #fff; padding: 28px 32px 30px; min-height: 250px; }
.part.person .fact .k { font-size: 23px; font-weight: 700; color: var(--muted); }
.part.person .fact .v { font-size: 60px; font-weight: 800; line-height: 1.15; color: var(--ink); margin-top: 12px; letter-spacing: -.02em; }
.part.person .fact .s { font-size: 21px; line-height: 1.55; color: var(--muted); margin-top: 14px; }
.part.person .fact.blank { border: 3px dashed #cbd5e1; background: #fafafa; padding: 26px 30px 28px; }   /* 테두리가 굵은 만큼 안쪽 여백을 줄여 글 위치를 맞춘다 */
.part.person .fact.blank .v { color: var(--faint); }
"""

# 통합 덱 자체 규칙 — 가져온 장(.imp)의 틀 · 상속 되돌리기 · 전체 쪽 번호표
EXTRA_GLOBAL_CSS = """
/* 담당자 슬라이드 틀(통합 덱) — 래퍼 .imp 는 1280×720 → 1920×1080 으로 키워 놓는다(크기 · 배율은 장마다 inline) */
.slide.has-imp { padding: 0; background: #fff; }
.imp { position: absolute; left: 0; top: 0; transform-origin: 0 0; overflow: hidden; }
:where(.imp) { font-family: initial; color: initial; word-break: normal; }   /* 영상 덱 html,body 의 상속(글꼴 · 글자색 · keep-all)을 되돌린다 — 담당자 덱의 body 규칙이 다시 정한다 */
.has-imp > .gnum { position: absolute; right: 28px; top: 10px; z-index: 5; display: flex; gap: 10px; align-items: center; font-size: 19px; line-height: 1.4;
  color: #64748b; background: rgba(255,255,255,.8); border: 1px solid rgba(100,116,139,.28); border-radius: 999px; padding: 3px 16px; pointer-events: none; }
.has-imp > .gnum b { font-weight: 700; }
/* 영상 장 오른쪽 설명 칸 — 목적 · 마지막 장 · 기준 글이 길면 아래 쪽번호까지 넘쳐 잘렸다(11-11 사용자 캡처). 폭을 넓히고 글자를 줄인다 */
.slide .video-side:not(:where(.imp *)) { width: 250px; font-size: 18px; line-height: 1.5; }
.slide .video-side b:not(:where(.imp *)) { font-size: 22px; margin-bottom: 4px; }
@media print { html { -webkit-print-color-adjust: exact; print-color-adjust: exact; } .has-imp > .gnum { display: none; } }
"""


@dataclass
class Plan:
  frames: list[Frame]
  people: list[dict]
  css: str
  reports: list[CssReport]
  audit: list[str]
  expected: int
  warnings: list[str]
  skipped_scenes: list[str]
  head: str
  tail: str


def make_plan() -> Plan:
  scenes = load_scenes()
  dur = load_durations()
  warnings: list[str] = []
  people = []
  for name in ORDER:
    p = read_personal(name)
    if p:
      warnings += [f"{name}: {w}" for w in p.warnings]
    people.append({"name": name, "personal": p, "vids": [r for r in scenes if r["owner"] == name]})
  skipped = [r["stem"] for r in scenes if r["owner"] not in ORDER]
  if skipped:
    warnings.append(f"owner 가 ORDER 에 없는 장면 {len(skipped)}개는 덱에서 뺐다: {', '.join(skipped)}")

  frames: list[Frame] = []
  meta: list[tuple[str, int] | None] = []          # frames 와 같은 순서 — 담당자 슬라이드는 (이름, 그 덱 안의 번호)
  tails: list[tuple[Personal, int, Slide]] = []    # 맨 끝으로 보낼 장(한계) — 모든 사람이 끝난 뒤 붙인다
  skipped_n = 0                                    # SKIP_SLIDES 로 뺀 슬라이드 수 — 장 수 기대값에서 뺀다
  by_name = {x["name"]: x["personal"] for x in people}
  tail_ns = {n: (TAIL_SLIDES.get(n, 0) if by_name[n] else 0) for n in ORDER}
  for no, x in enumerate(people, 1):
    p, vids, name = x["personal"], x["vids"], x["name"]
    k = tail_ns[name]
    p_main = dataclasses.replace(p, slides=p.slides[:len(p.slides) - k]) if (p and k) else p
    if k:
      tnote = f"한계 {k}장은 통합 덱 맨 끝으로 옮겨 {TAIL_PRESENTER} 님이 발표"
    elif name == TAIL_PRESENTER and any(tail_ns.values()):
      tnote = f"맨 끝에서 {TAIL_LABEL} {sum(tail_ns.values())}장을 발표(자료는 {', '.join(n for n in ORDER if tail_ns[n])} 슬라이드에서 옴)"
    else:
      tnote = ""
    skip_view = SKIP_SLIDES.get(name, set())
    p_view = dataclasses.replace(p_main, slides=[sl for i, sl in enumerate(p_main.slides, 1) if i not in skip_view]) if p_main else p_main
    frames.append(Frame("divider", name, f"{name} 구분 장", divider(name, no, len(people), p_view, sorted(vids, key=lambda r: VIDEO_ORDER.index(r["stem"]) if r["stem"] in VIDEO_ORDER else len(VIDEO_ORDER)), dur, tnote), "own")); meta.append(None)
    inline = {}                                      # 슬라이드 번호 → 그 뒤에 끼울 영상들
    for r in vids:
      at = INLINE_VIDEOS.get(r["stem"])
      if at and at[0] == name:
        inline.setdefault(at[1], []).append(r)
    for rs in inline.values():                       # 같은 자리의 영상은 VIDEO_ORDER 순서로
      rs.sort(key=lambda r: VIDEO_ORDER.index(r["stem"]) if r["stem"] in VIDEO_ORDER else len(VIDEO_ORDER))
    inline_stems = {r["stem"] for rs in inline.values() for r in rs}
    if p:
      skip = SKIP_SLIDES.get(name, set())
      out_of_range = sorted(n for n in skip if n < 1 or n > len(p_main.slides))
      if out_of_range:
        raise SystemExit(f"멈춤: SKIP_SLIDES 의 {name} 번호 {out_of_range} 가 슬라이드 범위(1 ~ {len(p_main.slides)}) 밖이다")
      skipped_n += len([i for i in range(1, len(p_main.slides) + 1) if i in skip])
      for i, sl in enumerate(p_main.slides, 1):
        if i in skip:
          continue                                   # 덱에서만 뺀다 — 원본 파일은 그대로
        for old, new in TEXT_PATCH.get((name, i), []):
          if sl.html.count(old) != 1:
            raise SystemExit(f"멈춤: {name} {i}장에서 치환할 문구 「{old}」 가 {sl.html.count(old)}곳 있다(기대 1)")
          sl = dataclasses.replace(sl, html=sl.html.replace(old, new))
        frames.append(Frame("slide", name, f"{sl.title}", imported_frame(p, i, sl), sl.notes_from, sl.seconds)); meta.append((name, i))
        for r in inline.get(i, []):
          frames.append(Frame("video", name, f"{r['stem']} · {r['title']}", video_slide(r), "own" if r["says"] else "")); meta.append(None)
      tails += [(p, len(p_main.slides) + j, sl) for j, sl in enumerate(p.slides[len(p_main.slides):], 1)]
    for r in vids:
      if r["stem"] in inline_stems and p:
        continue
      frames.append(Frame("video", name, f"{r['stem']} · {r['title']}", video_slide(r), "own" if r["says"] else "")); meta.append(None)
  for p, i, sl in tails:
    frames.append(Frame("slide", TAIL_PRESENTER, f"{TAIL_LABEL} · {sl.title}",
                        imported_frame(p, i, sl, label=f"{TAIL_LABEL} · {TAIL_PRESENTER} 발표", owner=TAIL_PRESENTER), sl.notes_from, sl.seconds)); meta.append((p.name, i))
  expected = 1 + sum(1 + (len(x["personal"].slides) if x["personal"] else 0) + len(x["vids"]) for x in people) - skipped_n
  frames.insert(0, Frame("cover", "", "표지", cover(people, sum(1 for f in frames if f.kind == "slide")), "own")); meta.insert(0, None)

  # 쪽 번호를 덱 전체 하나로 — 담당자 덱 안의 번호(「3 / 29」 · 「10 · 」 · 「12장」)가 섞여 보이지 않게 한다.
  total_n = len(frames)
  loc2glob: dict[str, dict[int, int]] = {}
  for g, mt in enumerate(meta, 1):
    if mt:
      loc2glob.setdefault(mt[0], {})[mt[1]] = g
  for g, (f, mt) in enumerate(zip(frames, meta), 1):
    if mt:
      f.html = fix_numbers(f.html, g, total_n, loc2glob[mt[0]])

  # 머리 · CSS · 스크립트
  base = BASE.read_text(encoding="utf-8").replace("\r\n", "\n")
  head = base[:base.index("<body>")]
  tail = base[base.index("<script>"):]
  base_css = head[head.index("<style>") + 7:head.index("</style>")]
  head = head.replace('<meta name="doc-version" content="1.2">', '<meta name="doc-version" content="0.2">', 1)
  head = head.replace("<title>Qurious 2차 발표</title>", "<title>Qurious 3차 발표</title>", 1)
  a, b = head.index("<!--\n"), head.index("-->\n") + 4
  head = head[:a] + ("<!--\n  3차 발표 통합 덱 v0.2 (2026-11-09 초안) — 이 파일은 tools/deck/build_team_deck.py 가 만든 원본이다. 손으로 고치지 않는다.\n"
                     "  장 순서: 표지 → 이동원(구분 장 · 슬라이드 · 영상) → 신장환 → 오준영 → 강민석. 슬라이드는 각자 <이름>/발표자료.html 에서, 영상은 videos/발표/P-*.yaml 에서 읽어 온다 —\n"
                     "  고칠 것은 그 원본이고, 고친 뒤 이 도구를 다시 돌린다. 넘기기: ← → · Space · N 말할 거리(대본 · 자막) · F 전체 화면 · 주소 끝 ?all = 모든 장 한 쪽.\n"
                     "  CSS: 영상 덱 규칙은 가져온 슬라이드(.imp) 안으로 새지 않게 :not(:where(.imp *)) 가드를, 담당자 덱 규칙은 래퍼(.d-lee · .d-oh …) 접두어를 붙여 가둔다.\n"
                     "  한 파일 판: python tools/deck/bundle_deck.py --src <이 파일> --out <전체-발표자료.html> — 영상 · 그림 · 글꼴을 파일 안에 넣어 HTML 하나만 옮겨도 재생된다.\n-->\n") + head[b:]

  reports: list[CssReport] = []
  rep_base = CssReport("영상 덱")
  parts = [guard_css(base_css, rep_base), guard_css(EXTRA_VD_CSS, rep_base)]
  reports.append(rep_base)
  parts.append(EXTRA_GLOBAL_CSS.strip())
  parts.append(video_player.PLAYER_CSS.strip())
  wrappers = []
  for x in people:
    p = x["personal"]
    if not p:
      continue
    w = f".d-{KEYS[p.name]}"
    wrappers.append(w)
    rep = CssReport(p.name)
    scoped = scope_import_css(p.css, w, KEYS[p.name] + "-", rep)
    reports.append(rep)
    warnings += [f"{p.name} CSS: {m}" for m in rep.warnings]
    parts.append(f"/* {p.name} 발표자료 CSS — {w} 안으로 가둠 (원본: {p.name}/발표자료.html v{p.version}) */\n{scoped}")
  css = "\n".join(parts)
  audit = audit_css(css, wrappers)

  # 넘기기 스크립트 — 영상 덱 것을 그대로 쓰되, 가져온 슬라이드 안의 원본 .slide 는 세지 않는다(#deck 바로 아래 틀만)
  old = "document.querySelectorAll('.slide')"
  if tail.count(old) != 1:
    raise SystemExit("멈춤: 넘기기 스크립트에서 querySelectorAll('.slide') 를 한 곳에서 찾지 못했다 — 2차 덱 원본이 바뀌었다")
  tail = tail.replace(old, "document.querySelectorAll('#deck > .slide')", 1)
  if tail.count("</body>") != 1:
    raise SystemExit("멈춤: 넘기기 스크립트 끝에서 </body> 를 한 곳에서 찾지 못했다 — 2차 덱 원본이 바뀌었다")
  tail = tail.replace("</body>", "<script>" + video_player.PLAYER_JS + "</script>\n</body>", 1)   # 영상 겹침 층 — 키 처리는 캡처 단계라 덱 기본보다 먼저
  return Plan(frames, people, css, reports, audit, expected, warnings, skipped, head, tail)


def render(plan: Plan) -> str:
  head = plan.head[:plan.head.index("<style>") + 7] + "\n" + plan.css + "\n" + plan.head[plan.head.index("</style>"):]
  slides = "\n\n".join(f.html for f in plan.frames)
  return (head + "<body>\n<div class=\"deck\" id=\"deck\">\n\n" + slides + "\n\n</div>\n<div id=\"notes-panel\"></div>\n"
          "<div id=\"hint\">← → 넘기기 · N 말할 거리 · F 전체 화면</div>\n" + plan.tail)


def verify(plan: Plan, text: str) -> list[str]:
  """만든 글의 빠른 점검 — 장 수 · id 중복 · 장마다 노트 하나."""
  errs: list[str] = []
  deck = text[text.index('<div class="deck" id="deck">'):text.index('<div id="notes-panel">')]
  top = len(re.findall(r'^<section class="slide[^>]*\sdata-title="', deck, re.M))   # 바깥 틀만(가져온 원본 section 에는 data-title 이 없다)
  if top != plan.expected or top != len(plan.frames):
    errs.append(f"장 수가 다르다: 기대 {plan.expected} · 틀 {len(plan.frames)} · 글 {top}")
  ids = re.findall(r'\bid="([^"]+)"', text)
  dup = sorted({i for i in ids if ids.count(i) > 1})
  if dup:
    errs.append(f"id 가 겹친다: {', '.join(dup[:8])}")
  for f in plan.frames:
    if f.html.count('<aside class="notes"') != 1:
      errs.append(f"노트가 정확히 1개가 아닌 장: {f.title}")
  if plan.audit:
    errs.append(f"가두지 않은 CSS 선택자 {len(plan.audit)}개: {', '.join(plan.audit[:5])}")
  return errs


def print_plan(plan: Plan) -> None:
  print("== 소스 ==")
  for x in plan.people:
    p, vids = x["personal"], x["vids"]
    if p:
      secs = p.total_seconds
      nsrc = {"html": 0, "md": 0, "js": 0, "": 0}
      for s in p.slides:
        nsrc[s.notes_from] += 1
      print(f"  {x['name']:<4} 슬라이드 {p.path.relative_to(ROOT).as_posix()} v{p.version} · {len(p.slides)}장 · {p.src_w}×{p.src_h} · 노트 html {nsrc['html']} / 발표대본.md {nsrc['md']} / JS배열 {nsrc['js']} / 없음 {nsrc['']}"
            f" · 대본 합계 {fmt_dur(secs)}")
    else:
      print(f"  {x['name']:<4} 슬라이드 없음 → 구분 장이 「{'슬라이드 준비 중' if vids else '준비 중'} — {x['name']}」")
    for r in vids:
      ok = (FILES / f"{r['stem']}.mp4").exists()
      print(f"       영상 {'✅' if ok else '·'} {r['stem']:<34} {'mp4 있음' if ok else 'mp4 없음'} · 자막 {len(r['says'])}줄")
  print("== 장 목록 ==")
  for i, f in enumerate(plan.frames, 1):
    ns = {"html": "노트 html", "md": "노트 대본.md", "js": "노트 JS배열", "own": "노트", "": "노트 없음"}[f.note_state]
    print(f"  {i:>2}. {f.kind:<7} {f.owner or '-':<4} {f.title[:60]}  [{ns}{f'·{f.seconds}초' if f.seconds else ''}]")
  print("== CSS 가두기 ==")
  for r in plan.reports:
    d = f" · 버림 {len(r.dropped)} ({', '.join(sorted(set(r.dropped))[:6])}…)" if r.dropped else ""
    print(f"  {r.label:<6} 규칙 {r.kept}{d}")
  print(f"  점검: 가두지 않은 선택자 {len(plan.audit)}개" + (f" — {', '.join(plan.audit[:5])}" if plan.audit else ""))
  parts = " + ".join(f"({1 + (len(x['personal'].slides) if x['personal'] else 0) + len(x['vids'])})" for x in plan.people)
  print(f"== 장 수 == 기대 {plan.expected} = 표지 1 + {parts}  ·  실제 {len(plan.frames)}")
  for w in plan.warnings:
    print(f"⚠️  {w}")


def main(argv: list[str] | None = None) -> int:
  ap = argparse.ArgumentParser(description="3차 발표 통합 덱 원본(표지 → 이동원 → 신장환 → 오준영 → 강민석)")
  ap.add_argument("--check", action="store_true", help="쓰지 않고 장 목록 · 파일 유무 · CSS 점검만")
  ap.add_argument("--out", type=Path, default=OUT, help="쓸 곳(기본: 전체-발표자료-원본.html)")
  args = ap.parse_args(argv)
  plan = make_plan()
  text = render(plan)
  errs = verify(plan, text)
  print_plan(plan)
  for e in errs:
    print(f"❌ {e}")
  if args.check:
    return 1 if errs else 0
  if errs:
    print("멈춤: 위 오류를 고친 뒤 다시 실행하세요 — 아무것도 쓰지 않았다")
    return 1
  out = args.out.resolve()
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_bytes(text.encode("utf-8"))
  shown = out.relative_to(ROOT).as_posix() if out.is_relative_to(ROOT) else str(out)
  print(f"썼습니다 {shown} · 장 {len(plan.frames)} · {len(text.encode('utf-8')) / 1024:.0f} KB")
  return 0


if __name__ == "__main__":
  sys.exit(main())
