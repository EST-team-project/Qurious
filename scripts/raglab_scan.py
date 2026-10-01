"""통합본 반입 폴더(`rag-lab/`) 실측 스캐너.

`rag-lab/` 은 개인 프로젝트 `investment-rag-lab`(강사님 domain-rag-lab 과 investment-analysis 를
합친 통합본)을 **AWS 만 빼고 통째로 옮겨 놓은 폴더**다. Qurious 앱과 아직 이어져 있지 않다 —
읽고, 화면을 새로 설계해, 기능 하나씩 `app/` · `public/` 으로 옮겨 오기 위한 자리다.

옮겨 놓기만 하면 두 가지가 조용히 틀어진다. 이 스캐너는 그 둘을 다시 잴 수 있게 한다.

1. **무엇이 들어왔나** — 누가 파일을 더하거나 고쳐도 표는 모른다. 그래서 파일마다 git blob ID 를
   대장(`docs/설계/통합본-반입대장.tsv`)에 적어 두고, 폴더와 대장이 같은지 본다.
   AWS 로 분류해 뺀 파일이 폴더에 들어오거나, 비공개 데이터셋에 둔 시세 자료가 커밋될 수 있는
   상태(.gitignore 에 없음)이면 알린다.
2. **무엇을 할 것인가** — 통합본의 화면과 API 를 늘어놓고(목록), 그 하나하나가 「어느 기능 묶음으로
   옮겨지는가」 를 이식 대장(`docs/설계/통합본-이식대장.tsv`)에 적는다. 어느 묶음에도 없는 화면 ·
   API 가 있으면 알린다 — 「전부 확인했다」 를 사람의 기억이 아니라 검사로 남긴다.

    python scripts/raglab_scan.py                       # 요약 + 두 대장 점검
    python scripts/raglab_scan.py --check               # 어긋난 곳이 있으면 종료코드 1
    python scripts/raglab_scan.py --md routes           # 표 하나 (routes · views · days · stores · ledger · bundles)
    python scripts/raglab_scan.py --json                # 기계용
    python scripts/raglab_scan.py --doc <문서>           # 문서의 <!-- raglab_scan:이름 --> 사이를 다시 채운다
    python scripts/raglab_scan.py --check-doc <문서>     # 다시 채울 곳이 있으면 종료코드 1

⚠️ 목록은 **정적으로 읽은 것**이다(앱을 띄우지 않는다). 「닿는 곳」 은 함수 본문과 같은 파일의 도움 함수
안에서 이름을 찾은 것이라, 다른 모듈을 거쳐 닿는 곳은 빠질 수 있다 — 옮길 때 그 기능의 코드를 직접 읽는다.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "rag-lab"
IMPORT_LEDGER = ROOT / "docs" / "설계" / "통합본-반입대장.tsv"
PORT_LEDGER = ROOT / "docs" / "설계" / "통합본-이식대장.tsv"
API_ID_LEDGER = ROOT / "docs" / "인터페이스" / "API-ID대장.tsv"

# 폴더 안에서 대장에 없어도 되는 파일 — 우리가 넣은 안내문 하나뿐이다.
GUIDE_FILE = "00-반입안내.md"

IMPORT_COLUMNS = ("경로", "크기", "blob", "영역", "종류", "원천", "상태", "사유")
# 복사      = 폴더에 있고 git 에 들어간다.
# AWS 제외  = 가져오지 않았다. 폴더에 있으면 안 된다.
# HF 보관   = git 에 넣지 않고 비공개 데이터셋에 둔 시세 자료. 받아 두면 폴더에 있을 수 있지만
#             .gitignore 에 적혀 있어야 한다(데이터 원본은 커밋하지 않는다).
STATE_COPIED, STATE_AWS, STATE_HF = "복사", "AWS 제외", "HF 보관"
IMPORT_STATES = (STATE_COPIED, STATE_AWS, STATE_HF)
GITIGNORE = ROOT / ".gitignore"

PORT_COLUMNS = ("묶음ID", "묶음", "화면", "API", "요구ID", "Qurious에_있는_것", "판정", "차례", "상태", "비고")
# 판정 = 화면을 설계할 때의 경우. Qurious 에 이미 있는 화면과 맞대어 고른다.
#   새 화면  Qurious 에 없는 기능 — 화면을 새로 설계한다
#   합침     비슷한 화면이 있다 — 그 화면에 칸 · 탭을 더한다
#   바꿈     Qurious 화면이 고정 값 · 빈 껍데기다 — 통합본 방식으로 다시 만든다
#   참고     Qurious 것이 더 나아가 있다 — 화면 구성만 본다
#   보류     요구 목록 밖이거나 팀이 정할 것
#   제외     가져오지 않는다(AWS · 계정처럼 Qurious 것이 정본)
#   흡수     Qurious 의 다른 부분이 이미 그 일을 해 옮길 것이 없다(2026-10-01 화면 자리 조사 — 「제외」 와 달리 기능은 있다)
PORT_VERDICTS = ("새 화면", "합침", "바꿈", "참고", "보류", "제외", "흡수")
PORT_PROGRESS = ("안 함", "설계", "구현", "끝")

HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# 함수 본문에서 찾는 이름 → 그 API 가 닿는 곳. 순서가 표에 적히는 순서다.
TOUCH_PATTERNS: tuple[tuple[str, str], ...] = (
    ("PostgreSQL", r"\bSession\b|Depends\(get_db\)|SessionLocal|db\.(query|execute|add|commit|get)\("),
    ("Mongo", r"get_db\(\)\[|\bmongo"),
    ("Qdrant", r"qdrant"),
    ("Redis", r"\bredis\b"),
    ("야후", r"yfinance|\byf\.|yahoo"),
    ("pykrx", r"pykrx"),
    ("네이버", r"naver"),
    ("DART", r"opendart|dart\.fss|_dart_api_key|DART_API_KEY"),
    ("KRX", r"krx\.co\.kr|_krx_auth_key"),
    ("LLM", r"ollama|vllm|LLMService|llm_service|RAG_LLM"),
    ("LEAN", r"\blean\b|LeanBacktest"),
    ("torch", r"\btorch\b|diffusers"),
    ("합성 데이터", r"np\.random|make_classification|make_blobs|make_moons|default_rng"),
    ("파일", r"read_text\(|UploadFile|FileResponse|open\("),
)

# 화면 코드에서 서버 주소로 보이는 글자 — 따옴표 · 백틱 안에서 이 머리로 시작하는 것만.
_PATH_LITERAL = re.compile(r"""['"`](/(?:api|market|auth|chat|ingest|backtests|files|health)\b[^'"`\s?]*)""")


# ─────────────────────────────────────────────────────────────────────
# 1. 반입 대장 ↔ 폴더
# ─────────────────────────────────────────────────────────────────────
def read_tsv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    """대장 한 장을 읽는다. 칸 이름이 다르면 멈춘다 — 조용히 어긋나는 것보다 낫다."""
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        if tuple(reader.fieldnames or ()) != columns:
            raise SystemExit(f"{path.name}: 칸이 {columns} 이어야 하는데 {reader.fieldnames} 다")
        return [dict(row) for row in reader]


def git_blob_ids(data: bytes) -> set[str]:
    """이 바이트가 git 에 저장될 때 될 수 있는 blob ID 들.

    Windows 작업 트리는 줄끝이 CRLF 일 수 있고(`core.autocrlf`), 다른 PC · 리눅스는 LF 다.
    git 은 글 파일을 LF 로 저장하므로, 줄끝을 LF 로 맞춘 값과 바이트 그대로의 값 둘을 다 계산해
    대장의 값이 그중 하나이면 같은 파일로 본다. git 을 부르지 않아 시험에서도 돈다.
    """
    def blob(b: bytes) -> str:
        return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()

    ids = {blob(data)}
    if b"\0" not in data[:8000]:              # git 과 같은 기준 — 앞부분에 NUL 이 없으면 글 파일
        ids.add(blob(data.replace(b"\r\n", b"\n")))
    return ids


def check_import(rows: list[dict[str, str]]) -> list[str]:
    """폴더가 반입 대장과 같은지 본다. 어긋난 곳을 사람이 읽는 문장으로 돌려준다."""
    problems: list[str] = []
    known = set()
    ignored = set(GITIGNORE.read_text(encoding="utf-8").splitlines()) if GITIGNORE.is_file() else set()
    for row in rows:
        rel, state = row["경로"], row["상태"]
        known.add(rel)
        path = FOLDER / rel
        if state not in IMPORT_STATES:
            problems.append(f"{rel}: 상태 「{state}」 는 {IMPORT_STATES} 중 하나여야 한다")
        elif state == STATE_COPIED:
            if not path.is_file():
                problems.append(f"{rel}: 대장에는 복사로 적혔는데 폴더에 없다")
            elif row["blob"] not in git_blob_ids(path.read_bytes()):
                problems.append(f"{rel}: 내용이 대장의 blob 과 다르다(폴더에서 고쳤나 · 옮기다 고쳤으면 대장의 상태를 바꾼다)")
        elif state == STATE_HF:
            # 받아 둔 PC 에서는 폴더에 있다. 그래도 커밋되면 안 되므로 .gitignore 에 그 경로가 있어야 한다.
            if f"{FOLDER.name}/{rel}" not in ignored:
                problems.append(f"{rel}: 「{state}」 인데 .gitignore 에 {FOLDER.name}/{rel} 줄이 없다 — 커밋될 수 있다")
            if path.is_file() and row["blob"] not in git_blob_ids(path.read_bytes()):
                problems.append(f"{rel}: 받아 둔 파일이 대장의 blob 과 다르다(비공개 데이터셋의 것과 다른 파일이다)")
        elif path.exists():
            problems.append(f"{rel}: 「{state}」 로 뺀 파일이 폴더에 들어와 있다 — {row['사유']}")
    if FOLDER.is_dir():
        for p in sorted(FOLDER.rglob("*")):
            rel = p.relative_to(FOLDER).as_posix()
            if p.is_file() and rel not in known and rel != GUIDE_FILE and "__pycache__" not in p.parts:
                problems.append(f"{rel}: 폴더에 있는데 대장에 없다")
    return problems


# ─────────────────────────────────────────────────────────────────────
# 2. 통합본의 API — 라우트 파일을 문법 트리로 읽는다(앱을 띄우지 않는다)
# ─────────────────────────────────────────────────────────────────────
def _router_prefix(tree: ast.Module) -> str:
    """`router = APIRouter(prefix="/market")` 의 prefix. 없으면 빈 글자."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if getattr(node.value.func, "id", "") == "APIRouter":
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        return str(kw.value.value)
    return ""


def _reachable_source(fn: ast.AST, helpers: dict[str, ast.AST], source: str) -> str:
    """함수 본문 + 그 함수가 부르는 같은 파일의 도움 함수 본문(끝까지 따라간다).

    라우트 함수는 보통 얇고 실제 일은 같은 파일의 `_load_…` · `_fetch_…` 가 한다.
    본문만 보면 「닿는 곳 없음」 으로 나와서, 같은 파일 안에서는 부르는 함수를 따라간다.
    """
    seen: set[str] = set()
    todo = [fn]
    parts: list[str] = []
    while todo:
        node = todo.pop()
        parts.append(ast.get_source_segment(source, node) or "")
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in helpers and sub.id not in seen:
                seen.add(sub.id)
                todo.append(helpers[sub.id])
    return "\n".join(parts)


def qurious_api() -> tuple[set[tuple[str, str]], set[str]]:
    """Qurious 가 이미 가진 API — (메서드, 경로 모양) 집합과 주소 묶음(앞 두 칸) 집합."""
    exact: set[tuple[str, str]] = set()
    groups: set[str] = set()
    if API_ID_LEDGER.exists():
        for line in API_ID_LEDGER.read_text(encoding="utf-8").splitlines()[1:]:
            cells = line.split("\t")
            if len(cells) >= 3:
                exact.add((cells[1], _shape(cells[2])))
                groups.add(_group(cells[2]))
    return exact, groups


def _shape(path: str) -> str:
    """경로 변수 이름을 지운 모양 — `/api/quiz/{id}` 와 `/api/quiz/{question_id}` 를 같게 본다."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _group(path: str) -> str:
    return "/".join(path.split("/")[:3])


def frontend_path_literals() -> dict[str, set[str]]:
    """화면 파일(JS · HTML)마다 그 안에 적힌 서버 주소들. 백틱 안 `${…}` 는 거기서 자른다."""
    found: dict[str, set[str]] = {}
    base = FOLDER / "frontend"
    if not base.is_dir():
        return found
    for p in sorted(base.rglob("*")):
        if p.suffix.lower() not in (".js", ".html") or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        literals = {m.group(1).split("${")[0] for m in _PATH_LITERAL.finditer(text)}
        if literals:
            found[p.relative_to(FOLDER).as_posix()] = literals
    return found


def _called_by(route_path: str, literals: dict[str, set[str]]) -> list[str]:
    """이 API 주소를 적어 둔 화면 파일들.

    화면 쪽 주소는 변수 자리에서 끊겨 있을 수 있다(`/api/quant/lean/` + 종목). 그래서 API 경로의
    변수 앞까지가 화면 글자와 같아도 「부른다」 로 본다.
    """
    pattern = re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(route_path)) + "/?$")
    head = route_path.split("{")[0]
    callers = []
    for file, paths in literals.items():
        if any(pattern.match(x) or ("{" in route_path and x == head) for x in paths):
            callers.append(file)
    return callers


def registered_route_modules() -> set[str]:
    """통합본 `app/main.py` 가 실제로 앱에 건 라우트 모듈 이름.

    라우트 파일이 있다고 그 API 가 살아 있는 것은 아니다 — `include_router` 로 걸지 않은 파일의 API 는
    서버에 없다(같은 주소를 정의한 파일이 둘이면 한쪽만 걸려 있다).
    """
    main_py = FOLDER / "app" / "main.py"
    if not main_py.is_file():
        return set()
    text = main_py.read_text(encoding="utf-8")
    alias = {m.group(2): m.group(1) for m in re.finditer(
        r"from app\.api\.routes\.([a-z_]+) import router as ([a-z_]+)", text)}
    return {alias[m.group(1)] for m in re.finditer(r"include_router\(([a-z_]+)\)", text) if m.group(1) in alias}


def scan_routes() -> list[dict]:
    rows: list[dict] = []
    route_dir = FOLDER / "app" / "api" / "routes"
    if not route_dir.is_dir():
        return rows
    exact, groups = qurious_api()
    literals = frontend_path_literals()
    registered = registered_route_modules()
    for py in sorted(route_dir.glob("*.py")):
        source = py.read_text(encoding="utf-8")
        tree = ast.parse(source)
        prefix = _router_prefix(tree)
        helpers = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for fn in helpers.values():
            for dec in fn.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                if dec.func.attr not in HTTP_METHODS or getattr(dec.func.value, "id", "") != "router":
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                path = prefix + str(dec.args[0].value)
                method = dec.func.attr.upper()
                body = _reachable_source(fn, helpers, source)
                touches = [name for name, pat in TOUCH_PATTERNS if re.search(pat, body, re.IGNORECASE)]
                if (method, _shape(path)) in exact:
                    overlap = "같은 주소"
                elif _group(path) in groups:
                    overlap = "같은 묶음"
                else:
                    overlap = "새 주소"
                doc = (ast.get_docstring(fn) or "").strip().splitlines()
                rows.append({
                    "method": method, "path": path, "file": py.name, "function": fn.name,
                    "summary": doc[0] if doc else "", "touches": touches,
                    "callers": _called_by(path, literals), "overlap": overlap,
                    "registered": py.stem in registered,
                })
    rows.sort(key=lambda r: (r["path"], r["method"]))
    return rows


# ─────────────────────────────────────────────────────────────────────
# 3. 통합본의 화면 — 세 벌(통합 껍데기 · 분석 화면 · 강의 사이트)
# ─────────────────────────────────────────────────────────────────────
class _NavParser(HTMLParser):
    """`data-view` 가 붙은 요소와 그 글자, 그리고 그 요소가 속한 접이식 구역(`toggleNav('이름')`)."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, str]] = []
        self._section = ""
        self._open: dict[str, str] | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        m = re.search(r"toggleNav\('([^']+)'\)", a.get("onclick") or "")
        if m:
            self._section = m.group(1)
        if self._open is not None:
            self._depth += 1
        elif a.get("data-view"):
            self._open = {"view": a["data-view"], "label": "", "section": self._section}
            self._depth = 0

    def handle_endtag(self, tag):
        if self._open is None:
            return
        if self._depth == 0:
            self._open["label"] = " ".join(self._open["label"].split())
            self.items.append(self._open)
            self._open = None
        else:
            self._depth -= 1

    def handle_data(self, data):
        if self._open is not None:
            self._open["label"] += data


def _nav_items(html_path: Path) -> list[dict[str, str]]:
    if not html_path.is_file():
        return []
    parser = _NavParser()
    parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    return parser.items


def _api_dictionary() -> dict[str, str]:
    """분석 화면의 `api.이름` → 서버 주소 (`frontend/analysis/js/api.js`)."""
    p = FOLDER / "frontend" / "analysis" / "js" / "api.js"
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8")
    return {m.group(1): m.group(2).split("${")[0].split("?")[0]
            for m in re.finditer(r"^\s*([A-Za-z]+)\s*:\s*\([^)]*\)\s*=>\s*apiFetch\([`'\"]([^`'\"]+)", text, re.M)}


def _view_file_paths(js_path: Path, api_dict: dict[str, str]) -> list[str]:
    """뷰 파일 하나가 부르는 서버 주소 — `api.이름(` 과 직접 적은 주소를 합친다."""
    if not js_path.is_file():
        return []
    text = js_path.read_text(encoding="utf-8", errors="replace")
    paths = {api_dict[m.group(1)] for m in re.finditer(r"\bapi\.([A-Za-z]+)\(", text) if m.group(1) in api_dict}
    paths |= {m.group(1).split("${")[0].split("?")[0] for m in _PATH_LITERAL.finditer(text)}
    return sorted(paths)


def scan_views() -> list[dict]:
    """화면 목록 — 어느 벌(껍데기 · 분석)의 어떤 키이고, 메뉴에 걸려 있는지, 어느 API 를 부르는지."""
    views: list[dict] = []
    front = FOLDER / "frontend"

    # (가) 통합 껍데기 — frontend/index.html 의 위 메뉴. 화면 코드는 frontend/app.js 한 파일이다.
    for item in _nav_items(front / "index.html"):
        views.append({"set": "통합", "view": item["view"], "label": item["label"], "menu": "위 메뉴",
                      "file": "frontend/app.js", "paths": []})

    # (나) 분석 화면 — app.js 의 routes 표가 정본이고, index.html 사이드바는 그 일부만 건다.
    app_js = front / "analysis" / "js" / "app.js"
    if app_js.is_file():
        text = app_js.read_text(encoding="utf-8")
        api_dict = _api_dictionary()
        # `import { quizHomeView, quizDayView } from './views/quiz.js'` 처럼 한 줄에 이름이 여럿일 수 있다.
        imports: dict[str, str] = {}
        for m in re.finditer(r"import\s*\{([^}]+)\}\s*from\s*'\./views/([A-Za-z]+\.js)'", text):
            for name in m.group(1).split(","):
                imports[name.strip()] = m.group(2)
        menu = {i["view"]: i["section"] or "구역 없음" for i in _nav_items(front / "analysis" / "index.html")}
        for m in re.finditer(r"^\s*'([a-z0-9-]+)':\s*\{\s*label:\s*'([^']+)',\s*render:\s*\(\)\s*=>\s*([A-Za-z]+)\(", text, re.M):
            key, label, func = m.groups()
            file = imports.get(func, "")
            rel = f"frontend/analysis/js/views/{file}" if file else ""
            views.append({"set": "분석", "view": key, "label": label, "menu": menu.get(key, "메뉴 없음"),
                          "file": rel, "paths": _view_file_paths(FOLDER / rel, api_dict) if rel else []})
        # 학습 문서 · 퀴즈 날짜는 표에 한 줄씩 풀어 적지 않고 코드가 만든다 — 같은 규칙으로 센다.
        docs_js = front / "analysis" / "js" / "data" / "learnDocs.js"
        if docs_js.is_file():
            learn_paths = _view_file_paths(front / "analysis" / "js" / "views" / "learn.js", api_dict)
            for d in re.finditer(r'"id":\s*"([^"]+)",\s*"file":\s*"[^"]+",\s*"title":\s*"[^"]*",\s*"label":\s*"([^"]+)"',
                                 docs_js.read_text(encoding="utf-8")):
                key = f"learn-{d.group(1)}"
                views.append({"set": "분석", "view": key, "label": f"학습 · {d.group(2)}",
                              "menu": menu.get(key, "메뉴 없음"), "file": "frontend/analysis/js/views/learn.js",
                              "paths": learn_paths})
        quiz = re.search(r"Array\.from\(\{\s*length:\s*(\d+)\s*\}[^\n]*\n\s*`quiz-day-", text)
        if quiz:
            quiz_rel = f"frontend/analysis/js/views/{imports.get('quizDayView', 'quiz.js')}"
            quiz_paths = _view_file_paths(FOLDER / quiz_rel, api_dict)
            for day in range(1, int(quiz.group(1)) + 1):
                key = f"quiz-day-{day}"
                views.append({"set": "분석", "view": key, "label": f"주식 {day} 퀴즈", "menu": menu.get(key, "메뉴 없음"),
                              "file": quiz_rel, "paths": quiz_paths})
        # 사이드바에는 걸려 있는데 routes 표에 없는 키 — 화면이 아니라 패널을 여는 위젯(차트 그리기)이 이렇게 걸린다.
        known = {v["view"] for v in views if v["set"] == "분석"}
        for key, section in menu.items():
            if key not in known:
                views.append({"set": "분석", "view": key, "label": "(routes 표에 없음 — 메뉴만)", "menu": section,
                              "file": "", "paths": []})
    # 통합 껍데기의 화면 여덟은 frontend/app.js 한 파일에 섞여 있어 화면별로 가를 수 없다.
    # 그 파일이 부르는 주소 전체를 여덟 줄에 똑같이 적는다(표를 읽을 때 「이 중 일부」 로 읽는다).
    shell_paths = sorted({p.split("?")[0] for p in frontend_path_literals().get("frontend/app.js", set())})
    for v in views:
        if v["set"] == "통합":
            v["paths"] = shell_paths
    return views


def scan_days() -> list[dict]:
    """강의 사이트 — 날짜별 HTML 한 장씩. 용어(`.glossary-item`)가 본문에 몇 개 박혀 있는지도 센다."""
    rows = []
    day_dir = FOLDER / "frontend" / "days"
    if not day_dir.is_dir():
        return rows
    for p in sorted(day_dir.glob("*.html")):
        text = p.read_text(encoding="utf-8", errors="replace")
        title = re.search(r"<title>(.*?)</title>", text, re.S)
        rows.append({
            "file": p.relative_to(FOLDER).as_posix(),
            "title": " ".join(title.group(1).split()) if title else "",
            "kb": round(len(text.encode("utf-8")) / 1024),
            "glossary": len(re.findall(r'class="glossary-item[" ]', text)),
            "paths": sorted({m.group(1).split("${")[0].split("?")[0] for m in _PATH_LITERAL.finditer(text)}),
        })
    return rows


# ─────────────────────────────────────────────────────────────────────
# 4. 통합본의 저장소 — 표 · 컬렉션
# ─────────────────────────────────────────────────────────────────────
def scan_stores() -> list[dict]:
    rows: list[dict] = []
    app_dir = FOLDER / "app"
    if not app_dir.is_dir():
        return rows
    for p in sorted(app_dir.rglob("*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(FOLDER).as_posix()
        for m in re.finditer(r'__tablename__\s*=\s*"([a-z_]+)"', text):
            rows.append({"store": "PostgreSQL", "name": m.group(1), "where": rel, "how": "SQLAlchemy 모델"})
        for m in re.finditer(r"CREATE TABLE(?: IF NOT EXISTS)?\s+([a-z_]+)", text, re.I):
            rows.append({"store": "PostgreSQL", "name": m.group(1), "where": rel, "how": "코드 안 SQL"})
        for name in sorted(set(re.findall(r"""get_db\(\)\[['"]([a-z_]+)['"]\]""", text))):
            rows.append({"store": "Mongo", "name": name, "where": rel, "how": "컬렉션"})
    for p in sorted(FOLDER.rglob("*.sql")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"CREATE TABLE(?: IF NOT EXISTS)?\s+([a-z_]+)", text, re.I):
            rows.append({"store": "PostgreSQL", "name": m.group(1), "where": p.relative_to(FOLDER).as_posix(),
                         "how": "SQL 파일"})
    seen, unique = set(), []
    for r in rows:                      # 같은 표가 모델과 SQL 에 함께 나오면 한 줄로
        key = (r["store"], r["name"], r["where"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ─────────────────────────────────────────────────────────────────────
# 5. 이식 대장 — 화면 · API 하나하나가 어느 묶음으로 가는가
# ─────────────────────────────────────────────────────────────────────
def _split(cell: str) -> list[str]:
    """대장 칸의 「가 · 나 · 다」 를 목록으로. 빈 칸 표시(「—」)는 빈 목록이다."""
    return [x.strip() for x in cell.split("·") if x.strip() and x.strip() != "—"]


def _matches(name: str, patterns: list[str]) -> bool:
    """`quiz-day-*` 처럼 끝이 * 인 무늬는 머리 일치, 아니면 글자 그대로."""
    return any(name.startswith(p[:-1]) if p.endswith("*") else name == p for p in patterns)


def check_port(bundles: list[dict[str, str]], routes: list[dict], views: list[dict]) -> list[str]:
    """모든 화면 · API 가 이식 대장의 묶음 **하나에만** 들어 있는지 본다."""
    problems: list[str] = []
    ids = [b["묶음ID"] for b in bundles]
    for dup in sorted(k for k, n in Counter(ids).items() if n > 1):
        problems.append(f"이식 대장: 묶음ID {dup} 가 두 번 나온다")
    for b in bundles:
        if b["판정"] not in PORT_VERDICTS:
            problems.append(f"이식 대장 {b['묶음ID']}: 판정 「{b['판정']}」 은 {PORT_VERDICTS} 중 하나여야 한다")
        if b["상태"] not in PORT_PROGRESS:
            problems.append(f"이식 대장 {b['묶음ID']}: 상태 「{b['상태']}」 는 {PORT_PROGRESS} 중 하나여야 한다")
    view_patterns = {b["묶음ID"]: _split(b["화면"]) for b in bundles}
    api_patterns = {b["묶음ID"]: _split(b["API"]) for b in bundles}
    for v in views:
        name = f"{v['set']}:{v['view']}"
        owners = [i for i, pats in view_patterns.items() if _matches(name, pats)]
        if len(owners) != 1:
            problems.append(f"화면 {name}: 묶음 {len(owners)}곳에 있다{owners} — 하나여야 한다")
    for r in routes:
        name = f"{r['method']} {r['path']}"
        owners = [i for i, pats in api_patterns.items() if _matches(name, pats) or _matches(r["path"], pats)]
        if len(owners) != 1:
            problems.append(f"API {name}: 묶음 {len(owners)}곳에 있다{owners} — 하나여야 한다")
    all_views = {f"{v['set']}:{v['view']}" for v in views}
    all_paths = {r["path"] for r in routes} | {f"{r['method']} {r['path']}" for r in routes}
    for b in bundles:                   # 대장에는 적혔는데 통합본에 없는 이름 — 오타이거나 이미 사라진 것
        for pat in view_patterns[b["묶음ID"]]:
            if not any(_matches(x, [pat]) for x in all_views):
                problems.append(f"이식 대장 {b['묶음ID']}: 화면 「{pat}」 가 통합본에 없다")
        for pat in api_patterns[b["묶음ID"]]:
            if not any(_matches(x, [pat]) for x in all_paths):
                problems.append(f"이식 대장 {b['묶음ID']}: API 「{pat}」 가 통합본에 없다")
    return problems


def bundle_counts(bundles, routes, views) -> list[dict]:
    """묶음마다 화면 · API 가 몇 개인지 — 문서 표에 넣는다."""
    out = []
    for b in bundles:
        vp, ap = _split(b["화면"]), _split(b["API"])
        out.append({**b,
                    "화면수": sum(1 for v in views if _matches(f"{v['set']}:{v['view']}", vp)),
                    "API수": sum(1 for r in routes if _matches(f"{r['method']} {r['path']}", ap) or _matches(r["path"], ap))})
    return out


# ─────────────────────────────────────────────────────────────────────
# 6. 표 찍기 · 문서 블록 채우기
# ─────────────────────────────────────────────────────────────────────
def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ") or "—"


def md_ledger(rows) -> str:
    total = Counter(r["상태"] for r in rows)
    size = Counter()
    for r in rows:
        size[r["상태"]] += int(r["크기"])
    lines = ["| 상태 | 파일 | 크기 |", "|---|--:|--:|"]
    for state in IMPORT_STATES:
        lines.append(f"| {state} | {total[state]} | {size[state] / 1048576:.1f} MB |")
    lines.append(f"| **합계** | **{sum(total.values())}** | **{sum(size.values()) / 1048576:.1f} MB** |")
    lines += ["", "| 영역 | 복사한 파일 | 크기 | 강사님 domain-rag-lab 과 같음 | 강사님 investment-analysis 와 같음 | 같은 경로 · 내용 다름 | 통합본 고유 |",
              "|---|--:|--:|--:|--:|--:|--:|"]
    areas: dict[str, Counter] = {}
    for r in rows:
        if r["상태"] != STATE_COPIED:
            continue
        c = areas.setdefault(r["영역"], Counter())
        c["n"] += 1
        c["bytes"] += int(r["크기"])
        origin = r["원천"]
        c["th07" if origin.startswith("강사님 domain-rag-lab 과 같음") else
          "th01" if origin.startswith("강사님 investment-analysis") else
          "diff" if "내용 다름" in origin else "own"] += 1
    for area in sorted(areas, key=lambda a: -areas[a]["bytes"]):
        c = areas[area]
        lines.append(f"| {area} | {c['n']} | {c['bytes'] / 1048576:.1f} MB | {c['th07']} | {c['th01']} | {c['diff']} | {c['own']} |")
    return "\n".join(lines)


def md_excluded(rows) -> str:
    lines = ["| 파일 | 상태 | 까닭 |", "|---|---|---|"]
    for r in rows:
        if r["상태"] != STATE_COPIED:
            lines.append(f"| `{r['경로']}` | {r['상태']} | {_cell(r['사유'])} |")
    return "\n".join(lines)


def md_routes(routes) -> str:
    lines = ["| 메서드 | 경로 | 파일 · 함수 | 앱에 걸림 | 닿는 곳 | 부르는 화면 파일 | Qurious 와 |", "|---|---|---|:-:|---|--:|---|"]
    for r in routes:
        lines.append(f"| {r['method']} | `{r['path']}` | `{r['file']}` · `{r['function']}` | "
                     f"{'예' if r['registered'] else '**아니오**'} | "
                     f"{' · '.join(r['touches']) or '—'} | {len(r['callers'])} | {r['overlap']} |")
    return "\n".join(lines)


def md_route_summary(routes) -> str:
    files: dict[str, Counter] = {}
    for r in routes:
        c = files.setdefault(r["file"], Counter())
        c["n"] += 1
        c["registered"] += 1 if r["registered"] else 0
        c["uncalled"] += 0 if r["callers"] else 1
        c[r["overlap"]] += 1
        for t in r["touches"]:
            c[f"t:{t}"] += 1
    lines = ["| 라우트 파일 | API | 앱에 걸림 | 화면이 안 부름 | Qurious 와 같은 주소 | 같은 묶음 | 닿는 곳 (그 파일의 API 중 몇 개) |",
             "|---|--:|:-:|--:|--:|--:|---|"]
    for file in sorted(files, key=lambda f: -files[f]["n"]):
        c = files[file]
        touch = " · ".join(f"{k[2:]} {v}" for k, v in c.most_common() if k.startswith("t:")) or "—"
        lines.append(f"| `{file}` | {c['n']} | {'예' if c['registered'] else '**아니오**'} | {c['uncalled']} | "
                     f"{c['같은 주소']} | {c['같은 묶음']} | {touch} |")
    lines.append(f"| **합계** | **{len(routes)}** | **{sum(1 for r in routes if r['registered'])}** | "
                 f"**{sum(1 for r in routes if not r['callers'])}** | "
                 f"**{sum(1 for r in routes if r['overlap'] == '같은 주소')}** | "
                 f"**{sum(1 for r in routes if r['overlap'] == '같은 묶음')}** | |")
    return "\n".join(lines)


def md_views(views) -> str:
    lines = ["| 벌 | 화면 키 | 이름 | 메뉴 | 코드 파일 | 부르는 API |", "|---|---|---|---|---|---|"]
    for v in views:
        paths = " · ".join(f"`{p}`" for p in v["paths"]) or "—"
        lines.append(f"| {v['set']} | `{v['view']}` | {_cell(v['label'])} | {v['menu']} | "
                     f"{('`' + v['file'].split('/')[-1] + '`') if v['file'] else '—'} | {paths} |")
    return "\n".join(lines)


def md_days(days) -> str:
    lines = ["| 파일 | 제목 | 크기 | 본문 속 용어 | 부르는 API |", "|---|---|--:|--:|---|"]
    for d in days:
        lines.append(f"| `{d['file']}` | {_cell(d['title'])} | {d['kb']} KB | {d['glossary']} | "
                     f"{' · '.join('`' + p + '`' for p in d['paths']) or '—'} |")
    return "\n".join(lines)


def md_stores(stores) -> str:
    lines = ["| 저장소 | 이름 | 정의한 곳 | 방식 |", "|---|---|---|---|"]
    for s in stores:
        lines.append(f"| {s['store']} | `{s['name']}` | `{s['where']}` | {s['how']} |")
    return "\n".join(lines)


def md_bundles(counted) -> str:
    lines = ["| 묶음 | 이름 | 화면 | API | 요구 ID | Qurious 에 있는 것 | 판정 | 차례 | 상태 |", "|---|---|--:|--:|---|---|:-:|:-:|:-:|"]
    for b in counted:
        lines.append(f"| {b['묶음ID']} | {_cell(b['묶음'])} | {b['화면수']} | {b['API수']} | {_cell(b['요구ID'])} | "
                     f"{_cell(b['Qurious에_있는_것'])} | {b['판정']} | {_cell(b['차례'])} | {b['상태']} |")
    lines.append(f"| **합계** | {len(counted)}묶음 | **{sum(b['화면수'] for b in counted)}** | "
                 f"**{sum(b['API수'] for b in counted)}** | | | | | |")
    return "\n".join(lines)


def build_blocks() -> dict[str, str]:
    ledger = read_tsv(IMPORT_LEDGER, IMPORT_COLUMNS)
    routes, views, days, stores = scan_routes(), scan_views(), scan_days(), scan_stores()
    blocks = {
        "ledger": md_ledger(ledger), "excluded": md_excluded(ledger),
        "route-summary": md_route_summary(routes), "routes": md_routes(routes),
        "views": md_views(views), "days": md_days(days), "stores": md_stores(stores),
    }
    if PORT_LEDGER.exists():
        blocks["bundles"] = md_bundles(bundle_counts(read_tsv(PORT_LEDGER, PORT_COLUMNS), routes, views))
    return blocks


_BLOCK = re.compile(r"(<!-- raglab_scan:([a-z-]+) -->\r?\n)(.*?)(<!-- /raglab_scan:\2 -->)", re.S)


def fill_document(text: str, blocks: dict[str, str]) -> str:
    """문서의 `<!-- raglab_scan:이름 -->` 과 `<!-- /raglab_scan:이름 -->` 사이를 다시 채운다.

    처음 쓰는 문서는 두 표시 줄 사이가 비어 있어도 된다. 문서의 줄끝(CRLF · LF)은 그대로 따른다.
    """
    newline = "\r\n" if "\r\n" in text else "\n"

    def repl(m: re.Match) -> str:
        name = m.group(2)
        if name not in blocks:
            raise SystemExit(f"문서에 모르는 블록이 있다: raglab_scan:{name}")
        return m.group(1) + blocks[name].replace("\n", newline) + newline + m.group(4)

    return _BLOCK.sub(repl, text)


def main(argv: list[str] | None = None) -> int:
    # git bash(mintty)에서는 표준출력이 cp949 가 된다 → ✅ · — 한 글자에서 죽는다. 도움말보다 먼저 맞춘다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="통합본 반입 폴더(rag-lab/) 실측 스캐너 — 앱을 띄우지 않고 읽는다")
    ap.add_argument("--check", action="store_true", help="두 대장과 폴더가 어긋나면 종료코드 1")
    ap.add_argument("--md", metavar="이름", help="표 하나를 찍는다 (ledger · excluded · route-summary · routes · views · days · stores · bundles)")
    ap.add_argument("--json", action="store_true", help="화면 · API · 저장소 목록을 JSON 으로")
    ap.add_argument("--doc", metavar="문서", help="문서의 raglab_scan 블록을 다시 채운다")
    ap.add_argument("--check-doc", metavar="문서", help="문서의 블록이 지금 값과 다르면 종료코드 1")
    args = ap.parse_args(argv)

    if not FOLDER.is_dir():
        print(f"반입 폴더가 없다: {FOLDER}")
        return 1
    if args.md:
        blocks = build_blocks()
        if args.md not in blocks:
            print(f"모르는 표: {args.md} (있는 표: {' · '.join(blocks)})")
            return 2
        print(blocks[args.md])
        return 0
    if args.json:
        print(json.dumps({"routes": scan_routes(), "views": scan_views(), "days": scan_days(),
                          "stores": scan_stores()}, ensure_ascii=False, indent=2))
        return 0
    if args.doc or args.check_doc:
        path = Path(args.doc or args.check_doc)
        # 바이트로 읽는다 — read_text 는 CRLF 를 LF 로 바꿔 읽어, 그대로 쓰면 파일의 줄끝이 통째로 바뀐다.
        before = path.read_bytes().decode("utf-8")
        after = fill_document(before, build_blocks())
        if args.check_doc:
            print("문서가 지금 값과 같다" if before == after else f"다시 채울 곳이 있다: {path}")
            return 0 if before == after else 1
        if before != after:
            path.write_bytes(after.encode("utf-8"))
        print(f"{'다시 채움' if before != after else '바뀐 곳 없음'}: {path}")
        return 0

    ledger = read_tsv(IMPORT_LEDGER, IMPORT_COLUMNS)
    routes, views, days, stores = scan_routes(), scan_views(), scan_days(), scan_stores()
    problems = check_import(ledger)
    if PORT_LEDGER.exists():
        problems += check_port(read_tsv(PORT_LEDGER, PORT_COLUMNS), routes, views)
    states = Counter(r["상태"] for r in ledger)
    print(f"반입 대장 {len(ledger)}줄 — 복사 {states[STATE_COPIED]} · AWS 제외 {states[STATE_AWS]} · HF 보관 {states[STATE_HF]}")
    print(f"API {len(routes)} (앱에 걸린 것 {sum(1 for r in routes if r['registered'])} · "
          f"화면이 안 부르는 것 {sum(1 for r in routes if not r['callers'])} · "
          f"Qurious 와 같은 주소 {sum(1 for r in routes if r['overlap'] == '같은 주소')})")
    sets = Counter(v["set"] for v in views)
    print(f"화면 {len(views)} (통합 {sets['통합']} · 분석 {sets['분석']}) · 강의 사이트 {len(days)}장 · 저장소 이름 {len(stores)}")
    if problems:
        print(f"⚠️ 어긋난 곳 {len(problems)}")
        for p in problems[:40]:
            print("  -", p)
        if len(problems) > 40:
            print(f"  … 외 {len(problems) - 40}곳")
    else:
        print("✅ 대장과 폴더가 같다")
    return 1 if (problems and args.check) else 0


if __name__ == "__main__":
    raise SystemExit(main())
