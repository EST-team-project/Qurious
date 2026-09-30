"""화면 정보구조(IA) 실측 스캐너.

IA 문서의 1절(지금 구조)은 「화면이 몇 개이고, 메뉴 어디에 있고, 들어가면 무엇을 부르는가」를
적는다. 사람이 손으로 옮기면 코드가 바뀌는 순간 표가 거짓이 된다 — A13(옛 #28)의 화면 표가
09-17 커밋 기준으로 굳어 있던 것처럼. 그래서 `public/app.html` 과 화면 스크립트를 다시
훑어 같은 표를 만든다. 네트워크를 쓰지 않는다.

화면 스크립트는 두 구조를 다 읽는다 — 옛 구조는 `app.html` 안 인라인 `<script type="module">` 한 덩어리
(+ `public/js/paper.js`), 2026-09-29 강사님 원본부터는 `public/js/*.js`(메뉴 · 안내 = core.js, 진입 훅 ·
첫 화면 = main.js, 기능별 파일)로 나뉘었다. 줄 위치는 `파일:줄` 로 적는다.

    python scripts/view_scan.py            # 요약 + 검사 결과
    python scripts/view_scan.py --md       # IA 문서 1.3절에 붙일 마크다운 표
    python scripts/view_scan.py --json     # 기계용

추출 규칙
- 화면: `<div class="view" data-view="X">` 줄부터 다음 화면 선언 직전까지(마지막은 `</main>` 전까지).
- 화면 소유 요소: 그 범위 안의 `id="..."`. 같은 id 가 두 번 나오면 먼저 나온 화면이 갖는다.
- 스크립트 블록: 0열에서 시작하는 문장 하나(함수 선언·리스너 등록 등).
- 진입 API: `on…ViewActivated`(onViewActivated · onPaperViewActivated · 기능별 훅)가 부르는 함수 + 그 함수가
  부르는 최상위 함수(1단계). 훅 모양은 `if (view === "X") …` 와 `if (view !== "X") return;` 뒤 호출 둘.
- 조작 API: 그 화면 소유 버튼에 걸린 리스너 블록(리스너가 아니면 그 화면 요소를 참조하는 블록)
  + 그 블록이 부르는 최상위 함수(1단계) − 진입 API.

⚠️ **판정하는 것은 「코드에 그렇게 적혀 있는가」이지 「브라우저에서 그렇게 도는가」가 아니다.**
API 대응은 요소 id 로 잇는 휴리스틱이라 2단계 이상 호출은 놓친다. 숨은 의존(다른 화면의 입력칸을
읽는 버튼)도 같은 규칙으로 잡으니, 보고된 줄은 사람이 코드로 한 번 더 확인한다.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "public" / "app.html"
JS_DIR = ROOT / "public" / "js"

VIEW_RE = re.compile(r'<div class="view" data-view="([^"]+)">')
ID_RE = re.compile(r'\bid="([^"$]+)"')
API_RE = re.compile(r'''\b(?:api|fetch)\(\s*[`"']([^`"'?$]+)''')
GETID_RE = re.compile(r'''getElementById\(\s*["']([^"']+)["']\s*\)''')
QS_RE = re.compile(r'''querySelector(?:All)?\(\s*["']#([A-Za-z0-9_-]+)''')
FUNC_RE = re.compile(r'^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(')
CONSTFN_RE = re.compile(r'^(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(')
CALL_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(')
LISTENER_RE = re.compile(r'''getElementById\(\s*"([^"]+)"\s*\)\??\.addEventListener\(\s*"([a-z]+)"''')
HOOK_RE = re.compile(r'if \(view === "([^"]+)"\)\s*(\{?)(.*)')
GUARD_RE = re.compile(r'if \(view !== "([^"]+)"\)\s*return;')
HOOK_FN_RE = re.compile(r'^(?:export\s+)?function\s+on[A-Za-z]*ViewActivated\s*\(')
MENU_DECL = ("const GNB_MENUS = {", "export const GNB_MENUS = {")
MENU_GROUP_RE = re.compile(r'^  ([a-z]+): \{$')
MENU_ITEM_RE = re.compile(r'\{ key: "([^"]+)",\s*icon: "[^"]+",\s*label: "([^"]+)" \}')
GNB_BUTTON_RE = re.compile(r'data-gnb="([a-z]+)"[^>]*>(?:<i[^>]*></i>)?\s*(?:<span>)?([^<]+)')
DEFAULT_VIEW_RE = re.compile(r'navigate\(hash && [^?]+\? hash : "([^"]+)"\)')

# D1 ③ 1차 분류 — **코드 사실이 아니라 제안**이다(논의 결정 대장 v0.9: ⏳ 2/4 미확정).
# 원문은 docs/github-archive/2026-09-15/논의-007/00-기록.md 3절 ③ 표. 메뉴 글자를 화면 ID 로 옮긴 것만 이 파일의 몫이다.
# 코드에 화면이 늘거나 줄면 --md 가 「미분류」로 드러낸다.
D1_PROPOSAL = {
  "주 경로": [
    "robo-portfolio", "robo-screening", "robo-decision", "paper-dashboard", "paper-stock",
    "quant-backtest", "quant-lean", "settings", "indicator-strategy", "indicator-custom",
    "indicator-backtest", "indicator-api",
  ],
  "최소 요건": ["ml-compare", "ml-cluster"],
  "개념 설명": [
    "fin-products", "fin-allocation", "quant-seasonal", "macro-dashboard", "macro-industry",
    "invest-fundamental", "invest-technical", "ml-regression", "ml-tune", "ml-deeplearning",
  ],
  "동결": [
    "agent-chat", "agent-cb", "agent-products", "agent-news",
    "crawl-auto", "crawl-manual", "crawl-ingest",
    "trading-chart", "trading-portfolio", "trading-order",
    "paper-crypto", "paper-alternative", "paper-openapi",
    "quant-dashboard", "quant-auto", "notification-settings",
    "us-dashboard", "us-chart", "us-order", "us-portfolio",
    "company-dashboard", "company-compare", "company-sector",
    "sysadmin-dashboard", "sysadmin-logs",
  ],
}
D1_OF = {key: cls for cls, keys in D1_PROPOSAL.items() for key in keys}


def _blocks(lines: list[str], start: int, label: str) -> list[dict]:
  """0열에서 시작하는 문장 하나를 블록으로 자른다."""
  out: list[dict] = []
  cur: dict | None = None
  for i in range(start, len(lines)):
    line = lines[i]
    if line.startswith("</script>"):
      break
    starts = bool(line) and not line[0].isspace() and not line.startswith(("}", ")", "//", "/*", "*", "]"))
    if starts:
      if cur:
        out.append(cur)
      m = FUNC_RE.match(line) or CONSTFN_RE.match(line)
      cur = {"file": label, "line": i + 1, "name": m.group(1) if m else None, "text": []}
    if cur:
      cur["text"].append(line)
  if cur:
    out.append(cur)
  for b in out:
    body = "\n".join(b.pop("text"))
    b["apis"] = sorted(set(API_RE.findall(body)))
    b["ids"] = sorted(set(GETID_RE.findall(body)) | set(QS_RE.findall(body)))
    b["calls"] = sorted(set(CALL_RE.findall(body)))
    b["listens"] = sorted({el for el, _ in LISTENER_RE.findall(body)})
  return out


def _script_sources(app: list[str]) -> tuple[list[tuple[str, list[str], int]], int]:
  """화면 스크립트 원천 — (라벨, 줄, 스크립트가 시작하는 줄 번호) 목록과 app.html 의 HTML 이 끝나는 줄.

  옛 구조의 인라인 `<script type="module">` 이 있으면 그것도 넣는다(없으면 app.html 전체가 HTML 이다).
  """
  inline = next((i for i, line in enumerate(app) if line.startswith('<script type="module">')), None)
  sources: list[tuple[str, list[str], int]] = []
  if inline is not None:
    sources.append(("app.html", app, inline + 1))
  for p in sorted(JS_DIR.glob("*.js")):
    sources.append((f"js/{p.name}", p.read_text(encoding="utf-8").splitlines(), 0))
  return sources, (inline if inline is not None else len(app))


def scan() -> dict:
  app = APP_PATH.read_text(encoding="utf-8").splitlines()
  sources, html_end = _script_sources(app)

  # 1. 화면 범위와 소유 요소
  views = [(m.group(1), i) for i, line in enumerate(app) if (m := VIEW_RE.search(line))]
  main_end = next(i for i, line in enumerate(app) if "</main>" in line and i > views[-1][1])
  view_range = {}
  for n, (key, start) in enumerate(views):
    end = views[n + 1][1] - 1 if n + 1 < len(views) else main_end - 1
    view_range[key] = (start, end)
  owner: dict[str, str] = {}
  for key, (s, e) in view_range.items():
    for line in app[s:e + 1]:
      for el in ID_RE.findall(line):
        owner.setdefault(el, key)

  # 2. 스크립트 블록
  blocks = [b for label, lines, start in sources for b in _blocks(lines, start, label)]
  by_name = {b["name"]: b for b in blocks if b["name"]}

  def closure(block: dict) -> set[str]:
    apis = set(block["apis"])
    for c in block["calls"]:
      if c in by_name and by_name[c] is not block:
        apis |= set(by_name[c]["apis"])
    return apis

  # 3. 진입 훅
  hooks: dict[str, list[str]] = {}
  hook_at: dict[str, str] = {}
  for label, lines, start in sources:
    inside, guard = False, None
    for i in range(start, len(lines)):
      line = lines[i]
      if HOOK_FN_RE.match(line):
        inside, guard = True, None
        continue
      if inside and line.startswith("}"):
        inside, guard = False, None
      if not inside:
        continue
      if m := HOOK_RE.search(line):
        fns = [c for c in CALL_RE.findall(m.group(3)) if c in by_name]
        hooks.setdefault(m.group(1), []).extend(fns)
        hook_at[m.group(1)] = f"{label}:{i + 1}"
      elif m := GUARD_RE.search(line):       # if (view !== "X") return; — 뒤 호출이 X 의 진입 훅이다
        guard = m.group(1)
        hook_at[guard] = f"{label}:{i + 1}"
      elif guard:
        fns = [c for c in CALL_RE.findall(line) if c in by_name]
        hooks.setdefault(guard, []).extend(fns)

  # 4. 메뉴(GNB_MENUS) · 상단 버튼 · 사용법 안내 · 첫 화면
  menu_label, menu_lines = next((label, lines) for label, lines, _ in sources
                                if any(line.startswith(MENU_DECL) for line in lines))
  menu_start = next(i for i, line in enumerate(menu_lines) if line.startswith(MENU_DECL))
  menu_end = next(i for i in range(menu_start, len(menu_lines)) if menu_lines[i] == "};")
  menu, group = [], None
  group_label: dict[str, str] = {}
  for i in range(menu_start, menu_end):
    line = menu_lines[i]
    if m := MENU_GROUP_RE.match(line):
      group = m.group(1)
    if group and "label:" in line and "key:" not in line:
      group_label[group] = re.sub(r"<[^>]+>", "", line.split('label: "', 1)[1].rsplit('"', 1)[0]).strip()
    if m := MENU_ITEM_RE.search(line):
      menu.append({"gnb": group, "key": m.group(1), "label": m.group(2), "menu_line": f"{menu_label}:{i + 1}"})
  gnb_buttons = [
    {"gnb": m.group(1), "label": m.group(2).strip(), "line": i + 1}
    for i, line in enumerate(app[:html_end]) if (m := GNB_BUTTON_RE.search(line))
  ]
  script_text = "\n".join(line for _, lines, start in sources for line in lines[start:])
  guides = set(re.findall(r'^  "([a-z-]+)":\s+\{ summary:', script_text, re.M))
  default_view = next((m.group(1) for line in script_text.splitlines() if (m := DEFAULT_VIEW_RE.search(line))), None)

  # 5. 화면별 행
  rows = []
  for n, item in enumerate(menu, 1):
    key = item["key"]
    fns = hooks.get(key, [])
    entry: set[str] = set()
    for f in fns:
      entry |= closure(by_name[f])
    action: set[str] = set()
    for b in blocks:
      if b["name"] in fns:
        continue
      # 리스너 블록은 버튼이 있는 화면의 조작으로만 센다 — 다른 화면 입력칸을 읽는다고 그 화면 API 가 되지는 않는다.
      trigger_views = {owner[t] for t in b["listens"] if t in owner}
      if trigger_views:
        if key in trigger_views:
          action |= closure(b)
      elif any(owner.get(el) == key for el in b["ids"]):
        action |= closure(b)
    s, e = view_range[key]
    rows.append({
      "n": n, **item,
      "group_label": group_label.get(item["gnb"], item["gnb"]),
      "view_lines": f"{s + 1}-{e + 1}",
      "hook": fns, "hook_at": hook_at.get(key),
      "entry_apis": sorted(entry), "action_apis": sorted(action - entry),
      "guide": key in guides, "d1": D1_OF.get(key, "미분류"),
    })

  # 6. 검사 — 숨은 의존(버튼이 다른 화면의 요소를 읽음) · 같은 리스너 중복 등록 · 화면 사이 링크
  # 한 블록이 여러 화면의 버튼을 함께 묶으면(예: 공용 종목 검색 창) 숨은 의존이 아니라 공용 부품으로 따로 적는다.
  hidden, shared = [], []
  for b in blocks:
    homes = sorted({owner[t] for t in b["listens"] if t in owner})
    if len(homes) > 1:
      shared.append({"at": f'{b["file"]}:{b["line"]}', "views": homes})
      continue
    for trigger in b["listens"]:
      home = owner.get(trigger)
      if not home:
        continue
      others = sorted({(owner[el], el) for el in b["ids"] if owner.get(el) not in (None, home)})
      if others:
        hidden.append({"at": f'{b["file"]}:{b["line"]}', "trigger": trigger, "view": home,
                       "reads": [f"{v}#{el}" for v, el in others]})
  listener_count = Counter(
    (el, ev) for _, lines, start in sources for line in lines[start:] for el, ev in LISTENER_RE.findall(line)
  )
  duplicates = [
    {"id": el, "event": ev, "count": c,
     "lines": [f"{label}:{i + 1}" for label, lines, start in sources for i, line in enumerate(lines)
               if i >= start and f'getElementById("{el}")' in line and "addEventListener" in line]}
    for (el, ev), c in listener_count.items() if c > 1
  ]
  link_re = re.compile(r'navigate\(\s*"[a-z-]+"\s*\)|href="#[a-z]|location\.hash\s*=\s*"')
  cross_links = [f"app.html:{i + 1}" for i, line in enumerate(app[:html_end]) if link_re.search(line)]
  cross_links += [f"{label}:{i + 1}" for label, lines, start in sources for i, line in enumerate(lines)
                  if i >= start and link_re.search(line)]

  return {
    "views": len(views), "menu_items": len(menu), "guides": len(guides),
    "hooked": sum(1 for r in rows if r["hook"]),
    "default_view": default_view,
    "gnb_buttons": gnb_buttons,
    "group_label": group_label,
    "not_in_menu": sorted({v for v, _ in views} - {m["key"] for m in menu}),
    "d1_counts": Counter(r["d1"] for r in rows),
    "hidden_dependencies": hidden,
    "shared_components": shared,
    "duplicate_listeners": duplicates,
    "cross_view_links": cross_links,
    "rows": rows,
  }


def _short(path: str) -> str:
  """`/api` 를 떼고, 경로 변수 자리(끝의 /)는 `…` 로 적는다."""
  p = path[4:] if path.startswith("/api/") else path
  return p + "…" if p.endswith("/") else p


def to_md(result: dict) -> str:
  head = ("| # | 묶음 | 화면 ID | 메뉴 글자 | 선언 줄 | 진입 훅 | 진입 API | 조작 API | D1 ③ (제안) |\n"
          "|---:|---|---|---|---|---|---|---|---|")
  lines = [head]
  for r in result["rows"]:
    entry = " · ".join(f"`{_short(a)}`" for a in r["entry_apis"]) or "—"
    action = " · ".join(f"`{_short(a)}`" for a in r["action_apis"]) or "—"
    hook = " + ".join(f"`{h}`" for h in r["hook"]) or "없음"
    lines.append(
      f'| {r["n"]} | {r["group_label"]} | `{r["key"]}` | {r["label"]} | {r["view_lines"]} '
      f'| {hook} | {entry} | {action} | {r["d1"]} |'
    )
  return "\n".join(lines)


def to_text(result: dict) -> str:
  out = [
    f'화면 선언 {result["views"]} · 메뉴 항목 {result["menu_items"]} · 사용법 안내 {result["guides"]}'
    f' · 진입 훅 {result["hooked"]} · 첫 화면 {result["default_view"]}',
    f'메뉴에 없는 화면: {result["not_in_menu"] or "없음"}',
    "D1 ③ 분류(제안): " + ", ".join(f"{k} {v}" for k, v in result["d1_counts"].items()),
    f'화면 사이 링크(navigate("…")·href="#…"): {len(result["cross_view_links"])}건',
    "",
    "[숨은 의존 — 버튼이 다른 화면의 요소를 읽는다]",
  ]
  out += [f'  {h["at"]}  #{h["trigger"]} ({h["view"]}) → {", ".join(h["reads"])}'
          for h in result["hidden_dependencies"]] or ["  없음"]
  out += ["", "[공용 부품 — 여러 화면의 버튼을 한 블록이 묶는다 (숨은 의존 아님)]"]
  out += [f'  {s["at"]}  {", ".join(s["views"])}' for s in result["shared_components"]] or ["  없음"]
  out += ["", "[같은 리스너 중복 등록]"]
  out += [f'  #{d["id"]} {d["event"]} ×{d["count"]}  줄 {d["lines"]}'
          for d in result["duplicate_listeners"]] or ["  없음"]
  return "\n".join(out)


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--md", action="store_true", help="IA 문서 1.3절용 마크다운 표")
  parser.add_argument("--json", action="store_true", help="기계용 JSON")
  args = parser.parse_args()
  result = scan()
  if args.json:
    print(json.dumps(result, ensure_ascii=False, indent=1))
  elif args.md:
    print(to_md(result))
  else:
    print(to_text(result))


if __name__ == "__main__":
  main()
