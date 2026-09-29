"""API 명세 실측 추출기 — API 명세서 · 인터페이스 정의서의 출처.

왜 이 파일이 있는가
-------------------
FastAPI 는 `/docs` 에 명세를 자동으로 그려 주지만, 그 화면은 **앱이 떠 있어야** 보이고
(서비스 5개 — collector README §2), 「이 API 가 어느 저장소 · 외부 서버에 닿는가 · 실거래
관문을 지나는가 · 수집 DB 다리를 타는가」는 보여 주지 않는다. 이 스크립트는 **앱을 import
하지 않고** `app/` 소스를 AST 로 읽어 라우트 전부를 표로 만든다. 네트워크도 쓰지 않는다.
API 명세서의 표는 이 출력을 붙인 것이고, 의심스러우면 다시 돌리면 된다.

    python scripts/api_scan.py                     # 요약 + 검사
    python scripts/api_scan.py --md                # API 명세서에 붙일 라우터별 표
    python scripts/api_scan.py --json              # 기계용
    python scripts/api_scan.py --openapi F.json    # 도커 안 app.openapi() 결과와 대조
    python scripts/api_scan.py --assign S63        # ID 대장에 없는 라우트에 새 ID (대장 파일을 고친다)

API ID 는 순번이 아니라 대장에서 온다
-------------------------------------
RTM 이 배운 것 — 순번으로 부르면 하나가 끼어드는 순간 뒤 번호가 전부 밀린다(RTM v1.0 §2.2).
그래서 ID 는 `docs/인터페이스/API-ID대장.tsv` 에 한 번 적으면 바뀌지 않는다. 라우트가
사라지면 줄을 지우지 않고 상태를 「폐기」 로 둔다(그 번호를 다시 쓰지 않는다).
기본 실행은 대장을 **읽기만** 하고, 고치는 것은 `--assign` 뿐이다.

「닿는 곳」 은 정적 호출 그래프다
---------------------------------
라우트 함수 **본문**에서 시작해 이름으로 풀리는 함수 · 클래스 · 모듈 상수를 따라간다
(가져오기 표 · 같은 모듈 · 패키지 재수출). 닿은 것 안에 무엇이 있느냐로 판정한다.

- 수집DB : `app.services.collector_db` 의 함수 (DF-08 다리)
- 증권사 : `brokers.factory.get_broker_client` — 실거래 관문(ADR-0001)이 이 함수 안에 있다
- 주문   : `.place_order(` 호출
- 외부 호스트 : 문자열 상수의 `http(s)://호스트` (모듈 상수 포함)
- 내부 시스템 : 가져온 모듈 이름 · `settings.X` 키 (PostgreSQL · Redis · Neo4j · Qdrant · LLM ·
  Celery · LEAN · Docker · 알림)

인증은 따로 본다 — 인자 기본값의 `Depends(...)` 를 풀어 **이름표**를 붙인다. 인증 의존성
이름을 먼저 모아 둔 이유: 옛 A3 가 `require_api_key` 를 빠뜨려 「인증 없는 라우트」 를
34 가 아니라 42 로 셌다.

한계 — 이 스크립트가 판정하지 않는 것
------------------------------------
- **런타임에 그 길을 타는가**는 모른다. `get_candles` 는 국내 주식 일봉이면 수집 DB, 아니면
  야후로 간다 — 「닿는 곳」 에는 둘 다 뜬다(가능한 길의 합집합).
- 인스턴스 메서드(`client.get_balance()`) · `getattr` · 문자열로 부르는 태스크는 이름으로 못 푼다.
  그래서 증권사는 **관문 함수에 닿는가**로 본다. 반대로 지역 변수가 가져온 이름을 가리면
  없는 길이 생길 수 있다(과대).
- 응답 모양은 `response_model` 이 없으면 모른다. 대신 본문의 `return {...}` 글자 키를 적는다.
  「`source`·`as_of` 가 실린다」 는 `X = await 다리에_닿는_함수(...)` 뒤 `return X` 인 경우만이다.
- 오류 코드는 **라우트 본문에 직접 적힌** `HTTPException`(과 그 하위 클래스)만 센다.
  서비스 안에서 던지는 것 · 인증 의존성의 401 · FastAPI 의 422 는 이 칸에 없다.
- 파트 칸은 **제안**이다 — 분배안 v1.0(옛 `#62`) §3 의 요구 → 파트 대응을 경로에 옮긴 것이지
  합의된 소유가 아니다(결정 대장 D0 ⑤ 역할 3/4).
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_REGISTRY_REL = Path("docs") / "인터페이스" / "API-ID대장.tsv"

HTTP_METHODS = ("get", "post", "put", "delete", "patch")
PARAM_FACTORIES = {"Query", "Path", "Body", "File", "Form", "Header", "Cookie"}
SPECIAL_PARAMS = {"Request", "Response", "BackgroundTasks", "WebSocket", "AsyncSession"}
RESPONSE_CLASSES = ("FileResponse", "StreamingResponse", "RedirectResponse", "JSONResponse", "HTMLResponse", "Response")
URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)")
# 호스트 글자 조각 → 시스템. 이 파일은 이 호스트를 부르지 않고 **찾기만** 한다(야후 봉인 시험 기준선의 주석).
HOST_SYSTEMS = (("yahoo", "야후"),)


def _host_system(host: str) -> str:
  return next((system for mark, system in HOST_SYSTEMS if mark in host), "외부")
PATH_PARAM_RE = re.compile(r"\{(\w+)(?::\w+)?\}")
FRONT_PATH_RE = re.compile(r"""[`"'](/(?:api|openapi)/[^`"'?$\s]*)""")

# 라우터 파일 → ID 머리글. 새 라우터 파일이 생기면 여기 한 줄을 더한다(없으면 --assign 이 멈춘다).
ROUTER_ABBR = {
  "auth": "AUTH", "ingest": "ING", "health": "HLTH", "chat": "CHAT", "stocks": "STK",
  "library": "LIB", "admin": "ADM", "system": "SYS", "quant": "QNT", "ml": "ML",
  "macro": "MACR", "documents": "DOC", "notification": "NOTI", "graph": "GRPH",
  "conversations": "CONV", "tasks": "TASK", "paper": "PAPR", "openapi": "OAPI", "lean": "LEAN",
}

# 인증 의존성 — 이름표. 값이 같은 모양이면 같은 사람이 통과한다.
AUTH_DEPENDENCIES = {
  "app.lib.session.get_current_user": "세션",
  "app.lib.jwt_auth.get_current_user_any": "세션·JWT",
  "app.lib.jwt_auth.get_current_user_jwt": "JWT",
  "app.routes.openapi.require_api_key": "API 키",
}
ROLE_FACTORIES = {"app.lib.jwt_auth.require_roles"}
DB_DEPENDENCIES = {"app.database.postgres.get_pg_session"}

# 가져온 이름의 출처 앞부분 → 내부 시스템.
IMPORT_SYSTEMS = (
  ("app.database.postgres", "PostgreSQL"),
  ("app.lib.redis_cache", "Redis"),
  ("redis", "Redis"),
  ("app.database.neo4j", "Neo4j"),
  ("neo4j", "Neo4j"),
  ("qdrant_client", "Qdrant"),
  ("langchain_qdrant", "Qdrant"),
  ("app.lib.ollama", "LLM"),
  ("app.lib.llm_client", "LLM"),
  ("langchain_ollama", "LLM"),
  ("app.celery_app", "Celery"),
  ("celery", "Celery"),
)
# `settings.X` 키 앞부분 → 내부 시스템.
SETTING_SYSTEMS = (
  ("REDIS_", "Redis"), ("NEO4J", "Neo4j"), ("QDRANT_", "Qdrant"), ("DOCUMENT_COLLECTION", "Qdrant"),
  ("OLLAMA_", "LLM"), ("VLLM_", "LLM"), ("LLM_", "LLM"), ("EMBED_MODEL", "LLM"), ("VLM_", "LLM"),
  ("LEAN_", "LEAN"), ("DOCKER_SOCK", "Docker"),
  ("TELEGRAM_", "알림"), ("SLACK_", "알림"), ("SMTP_", "알림"), ("KAKAO_", "알림"),
  ("COOLSMS_", "알림"), ("SMS_", "알림"),
)
SYSTEM_ORDER = (
  "수집DB", "야후", "증권사", "주문", "PostgreSQL", "Redis", "Neo4j", "Qdrant", "LLM",
  "Celery", "LEAN", "Docker", "알림", "외부",
)

# 파트 제안 — (라우터 파일, 경로 앞부분) → (파트, 분배안 근거). 위에서부터 처음 맞는 줄.
# 원문: docs/github-archive/2026-09-21/이슈-062/00-기록.md §3.1 · §3.2 · §3.3 · §4.
PART_RULES = (
  ("stocks", "/api/stocks/quant/indicators", "P-B", "P01-②-1 지표"),
  ("stocks", "/api/stocks/signals", "P-B", "P01-②-2 · ②-3 패턴 · 신호"),
  ("stocks", "/api/stocks", "P-A", "P01-①-2 시세 · 재무 · 검색"),
  ("stocks", "/api/custom-indicators", "P-B", "P02-②-3 인디케이터 버전 저장"),
  ("stocks", "/api/quant/pipeline", "P-D", "P02-①-3 백테스트 (P-B 경계 — 커스텀 인디케이터)"),
  ("stocks", "/api/portfolio", "P-E", "P01-④-3 포트폴리오 운용 (P-C 경계 — 시각적 포트폴리오)"),
  ("stocks", "/api/orders", "P-E", "P01-④-3 모의 주문"),
  ("stocks", "/api/broker", "P-E", "P02-⑤-1 계좌 · 시세 · 주문"),
  ("stocks", "/api/quant/settings", "P-E", "P02-⑤-1 · ⑤-2 자동매매 설정"),
  ("stocks", "/api/auto-trade", "P-E", "P02-⑤-1 · ⑤-2 자동매매"),
  ("stocks", "/api/quant/auto", "P-E", "P02-⑤-1 · ⑤-2 자동매매"),
  ("paper", "/api/paper/api-keys", "P-B", "P02-②-3 API 제공 — 키 발급"),
  ("paper", "", "P-E", "P01-④-3 모의 주문 체결"),
  ("openapi", "/openapi/v1/stocks", "P-B", "P02-②-3 API 제공"),
  ("openapi", "/openapi/v1/quote", "P-B", "P02-②-3 API 제공"),
  ("openapi", "/openapi/v1/docs-summary", "P-B", "P02-②-3 API 제공"),
  ("openapi", "", "P-E", "P01-④-3 모의 계좌 · 주문 (외부 제공 — P-B 경계)"),
  ("lean", "", "P-D", "P02-③-2 LEAN 교차검증"),
  ("quant", "", "P-D", "P02-①-3 · ④-2 파이프라인 성과"),
  ("ml", "/api/ml/robo/allocation", "P-C", "P01-③ 자산배분"),
  ("ml", "/api/ml/cluster", "P-C", "P01-③ 스크리닝"),
  ("ml", "", "P-D", "P02-①-3 · ④-2 모델 검증"),
  ("macro", "", "P-A", "P01-①-2 거시 수집"),
  ("chat", "", "P-A", "P01-①-3 RAG 질의응답"),
  ("conversations", "", "P-A", "P01-①-3 대화 이력"),
  ("documents", "", "P-A", "P01-①-3 근거 문서"),
  ("ingest", "", "P-A", "P01-①-2 · ①-4 적재 · 정기배치"),
  ("graph", "", "P-A", "P01-①-1 연관개념 탐색"),
  ("library", "", "P-A", "P01-①-2 자료 검색"),
  ("notification", "", "P-B", "P02-③-3 알림 (보조 P-E)"),
  ("tasks", "", "P-E", "P02-⑤-3 실행 · 로그"),
  ("system", "", "P-E", "P02-⑤-3 운영"),
  ("health", "", "P-E", "P02-⑤-3 운영"),
  ("auth", "", "공통", "분배안에 없음 — D3 ⑥ 인증 구조"),
  ("admin", "", "공통", "분배안에 없음 — D3 ③ 권한 경계"),
)


# ── 자료 구조 ───────────────────────────────────────────────────────

@dataclass
class Param:
  name: str
  kind: str            # path | query | body | file | form | header | cookie
  type: str = ""
  required: bool = False
  default: str = ""


@dataclass
class Route:
  api_id: str
  router: str          # 라우터 파일 이름 (stocks)
  method: str          # GET
  path: str            # /api/stocks/candles
  func: str
  file: str            # app/routes/stocks.py
  line: int
  summary: str = ""
  auth: str = "없음"
  uses_db_session: bool = False
  params: list[Param] = field(default_factory=list)
  body_models: list[str] = field(default_factory=list)
  response_model: str = ""
  status_code: str = ""
  response_kind: str = ""        # FileResponse 등 · 모델 없으면 빈칸
  return_keys: list[str] = field(default_factory=list)
  errors: list[str] = field(default_factory=list)
  reaches: list[str] = field(default_factory=list)
  hosts: list[str] = field(default_factory=list)
  bridge_passthrough: bool = False
  route_cache_hours: str = ""    # 라우트 본문이 직접 cache_get 을 부르면 그 max_age_hours
  cache_after_bridge: bool = False  # 캐시를 보기 전에 collector_db.handles(...) 로 다리 요청을 돌려보낸다 (DF-17)
  in_schema: bool = True
  part: str = ""
  part_basis: str = ""
  screens: list[str] = field(default_factory=list)   # 부르는 화면(IA view 키) — attach_screens
  in_frontend: bool = False                          # public/ 어디에든 경로 글자가 나오는가
  requirements: list[str] = field(default_factory=list)  # 이 API 가 받는 요구 ID — 기능 설계서 부록 A


@dataclass
class Node:
  """호출 그래프의 점 — 함수 · 클래스 · 모듈 상수."""
  qual: str
  module: str
  refs: set[str] = field(default_factory=set)      # 풀린 이름(노드가 아닐 수도 있다)
  settings: set[str] = field(default_factory=set)
  hosts: set[str] = field(default_factory=set)
  places_order: bool = False
  celery_call: bool = False


# ── 모듈 읽기 · 이름 풀기 ────────────────────────────────────────────

def _module_name(root: Path, path: Path) -> str:
  parts = list(path.relative_to(root).with_suffix("").parts)
  if parts[-1] == "__init__":
    parts = parts[:-1]
  return ".".join(parts)


def _dotted(expr: ast.AST) -> str | None:
  parts: list[str] = []
  while isinstance(expr, ast.Attribute):
    parts.append(expr.attr)
    expr = expr.value
  if isinstance(expr, ast.Name):
    parts.append(expr.id)
    return ".".join(reversed(parts))
  return None


def _call_name(call: ast.AST) -> str:
  """`Depends(x)` · `fastapi.Depends(x)` → 'Depends'."""
  if isinstance(call, ast.Call):
    d = _dotted(call.func)
    return d.rsplit(".", 1)[-1] if d else ""
  return ""


class _BodyVisitor(ast.NodeVisitor):
  """본문에서 이름 참조 · URL · 특이 호출을 모은다. 가장 긴 점 이름만 적는다."""

  def __init__(self) -> None:
    self.names: set[str] = set()
    self.hosts: set[str] = set()
    self.places_order = False
    self.celery_call = False

  def visit_Attribute(self, node: ast.Attribute) -> None:
    d = _dotted(node)
    if d:
      self.names.add(d)
    else:
      self.generic_visit(node)

  def visit_Name(self, node: ast.Name) -> None:
    self.names.add(node.id)

  def visit_Call(self, node: ast.Call) -> None:
    if isinstance(node.func, ast.Attribute):
      if node.func.attr == "place_order":
        self.places_order = True
      if node.func.attr in ("delay", "apply_async"):
        self.celery_call = True
    self.generic_visit(node)

  def visit_Constant(self, node: ast.Constant) -> None:
    if isinstance(node.value, str):
      self.hosts.update(URL_RE.findall(node.value))


def _visit_body(stmts: list[ast.stmt]) -> _BodyVisitor:
  v = _BodyVisitor()
  for s in stmts:
    v.visit(s)
  return v


class Codebase:
  """`app/` 전체를 AST 로 읽어 이름을 푸는 곳. 아무것도 import 하지 않는다."""

  def __init__(self, root: Path) -> None:
    self.root = root
    self.trees: dict[str, ast.Module] = {}
    self.files: dict[str, str] = {}
    for p in sorted((root / "app").rglob("*.py")):
      if "__pycache__" in p.parts:
        continue
      mod = _module_name(root, p)
      self.trees[mod] = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
      self.files[mod] = p.relative_to(root).as_posix()
    self.packages = {m for m in self.trees if self.files[m].endswith("__init__.py")}
    self.imports: dict[str, dict[str, str]] = {m: self._imports(m, t) for m, t in self.trees.items()}
    self.local: dict[str, set[str]] = {}
    self.nodes: dict[str, Node] = {}
    self.defs: dict[str, ast.AST] = {}
    self._reach_memo: dict[str, tuple[list[str], list[str]]] = {}
    for mod, tree in self.trees.items():
      self._collect_nodes(mod, tree)
    for node in self.nodes.values():
      self._link(node)

  # 가져오기 표 — 함수 안의 늦은 import 도 모듈 전체의 이름으로 본다.
  def _imports(self, mod: str, tree: ast.Module) -> dict[str, str]:
    table: dict[str, str] = {}
    pkg = mod if mod in self.packages else mod.rsplit(".", 1)[0]
    for n in ast.walk(tree):
      if isinstance(n, ast.Import):
        for a in n.names:
          if a.asname:
            table[a.asname] = a.name
          else:
            table[a.name.split(".")[0]] = a.name.split(".")[0]
      elif isinstance(n, ast.ImportFrom):
        if n.level:
          base_parts = pkg.split(".")
          base_parts = base_parts[: len(base_parts) - (n.level - 1)]
          base = ".".join(base_parts + ([n.module] if n.module else []))
        else:
          base = n.module or ""
        for a in n.names:
          table[a.asname or a.name] = f"{base}.{a.name}"
    return table

  def _collect_nodes(self, mod: str, tree: ast.Module) -> None:
    names: set[str] = set()
    for s in tree.body:
      if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(s.name)
        self.defs[f"{mod}.{s.name}"] = s
      elif isinstance(s, (ast.Assign, ast.AnnAssign)):
        targets = s.targets if isinstance(s, ast.Assign) else [s.target]
        for t in targets:
          if isinstance(t, ast.Name):
            names.add(t.id)
            self.defs[f"{mod}.{t.id}"] = s
    self.local[mod] = names
    # 설정 모듈은 점으로 두지 않는다 — 기본값 URL 이 `settings` 를 쓰는 모든 함수에 번진다.
    if mod == "app.config":
      return
    for name in names:
      self.nodes[f"{mod}.{name}"] = Node(qual=f"{mod}.{name}", module=mod)

  def resolve(self, mod: str, dotted: str) -> str | None:
    head, _, rest = dotted.partition(".")
    if head in self.local.get(mod, ()):
      q = f"{mod}.{head}"
    elif head in self.imports.get(mod, {}):
      q = self.imports[mod][head]
    else:
      return None
    if rest:
      q = f"{q}.{rest}"
    return self.canonical(q)

  def canonical(self, q: str) -> str:
    """패키지 재수출을 따라가 노드 이름으로 맞춘다. 노드가 아니면 풀린 글자 그대로."""
    for _ in range(6):
      if q in self.nodes:
        return q
      parts = q.split(".")
      moved = False
      for i in range(len(parts) - 1, 0, -1):
        m = ".".join(parts[:i])
        if m not in self.trees:
          continue
        head = f"{m}.{parts[i]}"
        if head in self.nodes:
          return head                          # Class.method → 클래스 점
        if parts[i] in self.imports[m]:
          q = ".".join([self.imports[m][parts[i]]] + parts[i + 1:])
          moved = True
        break
      if not moved:
        return q
    return q

  def _link(self, node: Node) -> None:
    d = self.defs[node.qual]
    if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef)):
      v = _visit_body(d.body)                  # 인자 기본값(Depends)은 인증 칸에서 따로 본다
    elif isinstance(d, ast.ClassDef):
      v = _visit_body(d.body)
      # 클래스 점은 메서드 전부를 한 몸으로 본다 — 「주문」 을 여기서 세면 시세 조회만 하는
      # 라우트도 주문으로 잡힌다(관문 함수가 증권사 클래스 일곱 개를 모두 가리키므로).
      v.places_order = False
    else:
      v = _BodyVisitor()
      if d.value is not None:
        v.visit(d.value)
    self._absorb(node, node.module, v)

  def _absorb(self, node: Node, mod: str, v: _BodyVisitor) -> None:
    for name in v.names:
      q = self.resolve(mod, name)
      if not q:
        continue
      if q.startswith("app.config.settings."):
        node.settings.add(q.split(".")[3])
        continue
      node.refs.add(q)
    node.hosts |= v.hosts
    node.places_order |= v.places_order
    node.celery_call |= v.celery_call

  def reach(self, start: Node) -> tuple[list[str], list[str]]:
    """start 에서 닿는 시스템 · 외부 호스트. 같은 점은 한 번만 계산한다."""
    if start.qual not in self._reach_memo:
      self._reach_memo[start.qual] = self._reach(start)
    return self._reach_memo[start.qual]

  def _reach(self, start: Node) -> tuple[list[str], list[str]]:
    seen = {start.qual}
    queue = deque([start])
    systems: set[str] = set()
    hosts: set[str] = set()
    while queue:
      n = queue.popleft()
      if n.module == "app.services.collector_db":
        systems.add("수집DB")
      if n.qual == "app.services.brokers.factory.get_broker_client":
        systems.add("증권사")
      if n.places_order:
        systems.add("주문")
      if n.celery_call:
        systems.add("Celery")
      for key in n.settings:
        for prefix, system in SETTING_SYSTEMS:
          if key.startswith(prefix):
            systems.add(system)
      hosts |= n.hosts
      for q in n.refs:
        for prefix, system in IMPORT_SYSTEMS:
          if q == prefix or q.startswith(prefix + "."):
            systems.add(system)
        nxt = self.nodes.get(q)
        if nxt and nxt.qual not in seen:
          seen.add(nxt.qual)
          queue.append(nxt)
    if any(_host_system(h) == "야후" for h in hosts):
      systems.add("야후")
    if "docker" in hosts:
      systems.add("Docker")                   # `http://docker` — 도커 소켓 위의 HTTP (lean_backtest)
    hosts = {h for h in hosts if "." in h}    # 점 없는 이름은 compose 안 서비스라 외부가 아니다
    if any(_host_system(h) == "외부" for h in hosts):
      systems.add("외부")
    ordered = [s for s in SYSTEM_ORDER if s in systems]
    return ordered, sorted(hosts)

  def is_pydantic_model(self, qual: str, depth: int = 0) -> bool:
    d = self.defs.get(qual)
    if not isinstance(d, ast.ClassDef) or depth > 5:
      return False
    mod = qual.rsplit(".", 1)[0]
    for b in d.bases:
      name = _dotted(b) or ""
      if name.rsplit(".", 1)[-1] == "BaseModel":
        return True
      q = self.resolve(mod, name) if name else None
      if q and self.is_pydantic_model(q, depth + 1):
        return True
    return False

  def model_fields(self, qual: str) -> list[dict[str, str]]:
    d = self.defs.get(qual)
    out: list[dict[str, str]] = []
    if isinstance(d, ast.ClassDef):
      for s in d.body:
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
          out.append({
            "이름": s.target.id,
            "타입": ast.unparse(s.annotation),
            "기본값": ast.unparse(s.value) if s.value is not None else "",
          })
    return out


# ── 라우트 뽑기 ─────────────────────────────────────────────────────

def _const(expr: ast.AST | None) -> object:
  if isinstance(expr, ast.Constant):
    return expr.value
  return None


def _kw(call: ast.Call, name: str) -> ast.AST | None:
  for k in call.keywords:
    if k.arg == name:
      return k.value
  return None


def _status_code(expr: ast.AST | None) -> str:
  v = _const(expr)
  if isinstance(v, int):
    return str(v)
  d = _dotted(expr) if expr is not None else None
  if d:
    m = re.search(r"HTTP_(\d{3})", d)
    if m:
      return m.group(1)
  return ""


def _registered_routers(cb: Codebase) -> list[str]:
  """main.py 의 include_router 순서. 여기 없는 라우터 파일은 앱에 붙지 않는다."""
  order: list[str] = []
  tree = cb.trees.get("app.main")
  if tree is None:
    return order
  for n in ast.walk(tree):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "include_router":
      d = _dotted(n.args[0]) if n.args else None
      if d:
        q = cb.resolve("app.main", d.split(".")[0])
        if q:
          order.append(q.rsplit(".", 1)[-1])
  return order


def _router_objects(cb: Codebase, mod: str) -> dict[str, dict]:
  """`router = APIRouter(prefix=..., dependencies=...)` → {이름: {prefix, deps}}."""
  found: dict[str, dict] = {}
  for s in cb.trees[mod].body:
    if isinstance(s, ast.Assign) and isinstance(s.value, ast.Call) and _call_name(s.value) == "APIRouter":
      prefix = _const(_kw(s.value, "prefix")) or ""
      deps = _kw(s.value, "dependencies")
      for t in s.targets:
        if isinstance(t, ast.Name):
          found[t.id] = {"prefix": prefix, "deps": deps.elts if isinstance(deps, ast.List) else []}
  return found


def _dependency_label(cb: Codebase, mod: str, dep_call: ast.Call, depth: int = 0) -> tuple[str, bool]:
  """`Depends(x)` 하나 → (인증 이름표 · DB 세션 여부). 모르는 의존성은 그 인자를 따라 들어간다."""
  if not dep_call.args or depth > 4:
    return "", False
  target = dep_call.args[0]
  if isinstance(target, ast.Call):             # Depends(require_roles("admin"))
    q = cb.resolve(mod, _dotted(target.func) or "") or ""
    if q in ROLE_FACTORIES:
      roles = "·".join(str(_const(a)) for a in target.args)
      return f"세션·JWT + 역할({roles})", False
    return "", False
  d = _dotted(target)
  q = cb.resolve(mod, d) if d else None
  if not q:
    return "", False
  if q in AUTH_DEPENDENCIES:
    return AUTH_DEPENDENCIES[q], False
  if q in DB_DEPENDENCIES:
    return "", True
  fn = cb.defs.get(q)
  if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
    inner_mod = q.rsplit(".", 1)[0]
    label, db = _args_dependencies(cb, inner_mod, fn)
    if label and _body_mentions(fn, "admin"):
      label = f"{label} + 관리자"
    return label, db
  return "", False


def _body_mentions(fn: ast.AST, word: str) -> bool:
  return any(isinstance(n, ast.Constant) and n.value == word for n in ast.walk(fn))


def _args_dependencies(cb: Codebase, mod: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, bool]:
  labels: list[str] = []
  db = False
  for _arg, default in _arg_defaults(fn):
    if isinstance(default, ast.Call) and _call_name(default) in ("Depends", "Security"):
      label, uses_db = _dependency_label(cb, mod, default)
      if label:
        labels.append(label)
      db |= uses_db
  return " · ".join(dict.fromkeys(labels)), db


def _arg_defaults(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.arg, ast.AST | None]]:
  a = fn.args
  positional = a.posonlyargs + a.args
  defaults: list[ast.AST | None] = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
  pairs = list(zip(positional, defaults))
  pairs += list(zip(a.kwonlyargs, a.kw_defaults))
  return pairs


def _params(cb: Codebase, mod: str, fn: ast.FunctionDef | ast.AsyncFunctionDef, path: str) -> tuple[list[Param], list[str]]:
  path_names = set(PATH_PARAM_RE.findall(path))
  params: list[Param] = []
  bodies: list[str] = []
  for arg, default in _arg_defaults(fn):
    ann = ast.unparse(arg.annotation) if arg.annotation is not None else ""
    base = re.split(r"[\[\|\s]", ann)[0].rsplit(".", 1)[-1] if ann else ""
    cname = _call_name(default) if isinstance(default, ast.Call) else ""
    if cname in ("Depends", "Security") or base in SPECIAL_PARAMS or arg.arg in ("self", "cls"):
      continue
    if cname in PARAM_FACTORIES:
      first = default.args[0] if default.args else _kw(default, "default")
      required = first is None or (isinstance(first, ast.Constant) and first.value is Ellipsis)
      dflt = "" if required else ast.unparse(first)
      kind = cname.lower()
      params.append(Param(arg.arg, kind, ann, required, dflt))
      continue
    if arg.arg in path_names:
      params.append(Param(arg.arg, "path", ann, True))
      continue
    # `Model | None` · `Optional[Model]` 도 본문이다 — 이름 조각 가운데 모델로 풀리는 것을 찾는다.
    q = next((r for r in (cb.resolve(mod, n) for n in re.findall(r"[A-Za-z_][\w\.]*", ann)
                          if n not in ("None", "Optional", "Union"))
              if r and cb.is_pydantic_model(r)), None)
    if q:
      bodies.append(q)
      params.append(Param(arg.arg, "body", q.rsplit(".", 1)[-1], default is None))
      continue
    if "UploadFile" in ann:
      params.append(Param(arg.arg, "file", ann, default is None))
      continue
    params.append(Param(arg.arg, "query", ann, default is None, "" if default is None else ast.unparse(default)))
  return params, bodies


def _errors(cb: Codebase, mod: str, fn: ast.AST) -> list[str]:
  """본문의 raise HTTPException(...) · 그 하위 클래스 → '404' · '401 UNAUTHORIZED'."""
  found: list[str] = []
  for n in ast.walk(fn):
    if not (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)):
      continue
    call = n.exc
    name = _dotted(call.func) or ""
    q = cb.resolve(mod, name) or name
    is_http = name.rsplit(".", 1)[-1] == "HTTPException"
    d = cb.defs.get(q)
    if isinstance(d, ast.ClassDef):
      is_http |= any((_dotted(b) or "").endswith("HTTPException") for b in d.bases)
    if not is_http:
      continue
    code = _status_code(call.args[0] if call.args else _kw(call, "status_code"))
    if not code:
      code = "?"
    tag = _const(call.args[1]) if len(call.args) > 1 and not name.endswith("HTTPException") else None
    found.append(f"{code} {tag}" if isinstance(tag, str) else code)
  return sorted(set(found), key=lambda s: (s[:3], s))


def _return_shape(fn: ast.AST) -> tuple[list[str], str]:
  keys: list[str] = []
  kind = ""
  for n in ast.walk(fn):
    if isinstance(n, ast.Return) and n.value is not None:
      v = n.value
      if isinstance(v, ast.Dict):
        for k in v.keys:
          if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value not in keys:
            keys.append(k.value)
      elif isinstance(v, ast.Call):
        cname = _call_name(v)
        if cname in RESPONSE_CLASSES:
          kind = cname
  return keys, kind


def _route_cache_hours(cb: Codebase, mod: str, fn: ast.AST) -> str:
  for n in ast.walk(fn):
    if isinstance(n, ast.Call) and _call_name(n) == "cache_get":
      hours = _kw(n, "max_age_hours")
      v = _const(hours)
      return str(v) if v is not None else "기본값"
  return ""


def _cache_after_bridge(fn: ast.AST) -> bool:
  """캐시를 보기 **전에** `collector_db.handles(...)` 로 다리 요청을 돌려보내는가 (DF-17).

  그러면 라우트 캐시는 옛 경로(야후 · DB 없음) 몫이라 다리의 `as_of` 를 가리지 않는다. 순서만 본다 —
  `handles` 호출이 첫 `cache_get` 보다 앞 줄에 있어야 참이다(캐시를 먼저 보면 옛 값이 이미 나간 뒤다).
  """
  calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
  gets = [n.lineno for n in calls if _call_name(n) == "cache_get"]
  gates = [n.lineno for n in calls if _dotted(n.func) == "collector_db.handles"]
  return bool(gets and gates) and min(gates) < min(gets)


def _carries_as_of(cb: Codebase, mod: str, fn: ast.AST, carriers: set[str], reaches_db: bool) -> bool:
  """이 함수의 응답에 다리의 `as_of` 가 실리는가 — 세 모양만 참으로 본다.

  ① `return {..., "as_of": ...}` 이고 수집 DB 에 닿는다 (`get_quant_indicators` 모양)
  ② `return [await] G(...)` 이고 G 가 싣는 함수다 — `asyncio.to_thread(G, ...)` 처럼 G 를
     첫 인자로 넘겨 돌리는 모양도 같다 (`collector_db.get_daily_candles` 모양)
  ③ `X = [await] G(...)` 뒤 `return X` 이고 G 가 싣는 함수다 (`get_candles` · 라우트 모양)
  다리에 닿기만 하고 결과를 바꿔 돌려주는 함수(모의투자 계좌 평가 등)는 거짓이다.
  """
  def callee(expr: ast.AST | None) -> str:
    v = expr.value if isinstance(expr, ast.Await) else expr
    if not isinstance(v, ast.Call):
      return ""
    q = cb.resolve(mod, _dotted(v.func) or "") or ""
    if q not in carriers and v.args:
      handed = cb.resolve(mod, _dotted(v.args[0]) or "") or ""
      if handed in carriers:
        return handed
    return q

  assigned: set[str] = set()
  for n in ast.walk(fn):
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
      if callee(n.value) in carriers:
        assigned.add(n.targets[0].id)
  for n in ast.walk(fn):
    if not (isinstance(n, ast.Return) and n.value is not None):
      continue
    v = n.value
    if reaches_db and isinstance(v, ast.Dict) and any(
        isinstance(k, ast.Constant) and k.value == "as_of" for k in v.keys):
      return True
    if callee(v) in carriers:
      return True
    if isinstance(v, ast.Name) and v.id in assigned:
      return True
  return False


def bridge_carriers(cb: Codebase) -> set[str]:
  """`as_of` 를 응답에 싣는 함수 전부 — 고정점까지 되풀이한다."""
  funcs = {q: d for q, d in cb.defs.items()
           if q in cb.nodes and isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef))}
  reaches_db = {q: "수집DB" in cb.reach(cb.nodes[q])[0] for q in funcs}
  carriers: set[str] = set()
  changed = True
  while changed:
    changed = False
    for q, d in funcs.items():
      if q not in carriers and _carries_as_of(cb, q.rsplit(".", 1)[0], d, carriers, reaches_db[q]):
        carriers.add(q)
        changed = True
  return carriers


def _part(router: str, path: str) -> tuple[str, str]:
  for r, prefix, part, basis in PART_RULES:
    if r == router and path.startswith(prefix):
      return part, basis
  return "미배정", ""


def extract_routes(cb: Codebase) -> list[Route]:
  routes: list[Route] = []
  registered = _registered_routers(cb)
  carriers = bridge_carriers(cb)
  route_mods = sorted((m for m in cb.trees if m.startswith("app.routes.") and m != "app.routes"),
                      key=lambda m: (registered.index(m.rsplit(".", 1)[-1]) if m.rsplit(".", 1)[-1] in registered else 999, m))
  for mod in route_mods:
    router_name = mod.rsplit(".", 1)[-1]
    objs = _router_objects(cb, mod)
    for s in cb.trees[mod].body:
      if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
      for dec in s.decorator_list:
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
          continue
        owner = _dotted(dec.func.value)
        if owner not in objs:
          continue
        verb = dec.func.attr
        if verb == "api_route":
          ms = _kw(dec, "methods")
          methods = [str(_const(e)).lower() for e in ms.elts] if isinstance(ms, ast.List) else ["get"]
        elif verb in HTTP_METHODS:
          methods = [verb]
        else:
          continue
        sub = _const(dec.args[0]) if dec.args else _const(_kw(dec, "path"))
        path = objs[owner]["prefix"] + (sub or "")
        label, uses_db = _args_dependencies(cb, mod, s)
        for dep in objs[owner]["deps"]:
          if isinstance(dep, ast.Call):
            l2, db2 = _dependency_label(cb, mod, dep)
            label = " · ".join(x for x in (l2, label) if x)
            uses_db |= db2
        params, bodies = _params(cb, mod, s, path)
        node = cb.nodes[f"{mod}.{s.name}"]
        reaches, hosts = cb.reach(node)
        if uses_db and "PostgreSQL" not in reaches:
          reaches = [x for x in SYSTEM_ORDER if x in set(reaches) | {"PostgreSQL"}]
        keys, kind = _return_shape(s)
        rm = _kw(dec, "response_model")
        in_schema = _const(_kw(dec, "include_in_schema"))
        doc = ast.get_docstring(s) or ""
        part, basis = _part(router_name, path)
        for m in methods:
          routes.append(Route(
            api_id="", router=router_name, method=m.upper(), path=path, func=s.name,
            file=cb.files[mod], line=dec.lineno, summary=doc.strip().splitlines()[0] if doc.strip() else "",
            auth=label or "없음", uses_db_session=uses_db, params=params,
            body_models=[b.rsplit(".", 1)[-1] for b in bodies],
            response_model=ast.unparse(rm) if rm is not None else "",
            status_code=_status_code(_kw(dec, "status_code")),
            response_kind=kind, return_keys=keys, errors=_errors(cb, mod, s),
            reaches=reaches, hosts=hosts, bridge_passthrough=f"{mod}.{s.name}" in carriers,
            route_cache_hours=_route_cache_hours(cb, mod, s), cache_after_bridge=_cache_after_bridge(s),
            in_schema=in_schema is not False, part=part, part_basis=basis,
          ))
  return routes


# ── ID 대장 ────────────────────────────────────────────────────────

REGISTRY_HEADER = ["API_ID", "메서드", "경로", "붙인_세션", "상태"]


def read_registry(root: Path) -> list[dict[str, str]]:
  p = root / ID_REGISTRY_REL
  if not p.exists():
    return []
  with p.open(encoding="utf-8", newline="") as f:
    return [row for row in csv.DictReader(f, delimiter="\t")]


def write_registry(root: Path, rows: list[dict[str, str]]) -> None:
  p = root / ID_REGISTRY_REL
  p.parent.mkdir(parents=True, exist_ok=True)
  with p.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=REGISTRY_HEADER, delimiter="\t", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)


def apply_registry(routes: list[Route], rows: list[dict[str, str]]) -> dict[str, list]:
  """대장의 ID 를 라우트에 붙인다. 대장은 고치지 않는다."""
  by_key = {(r["메서드"], r["경로"]): r for r in rows if r.get("상태") != "폐기"}
  for rt in routes:
    row = by_key.get((rt.method, rt.path))
    rt.api_id = row["API_ID"] if row else ""
  live = {(rt.method, rt.path) for rt in routes}
  return {
    "미등록": [f"{rt.method} {rt.path}" for rt in routes if not rt.api_id],
    "대장에만": [f'{r["API_ID"]} {r["메서드"]} {r["경로"]}' for r in rows
               if r.get("상태") != "폐기" and (r["메서드"], r["경로"]) not in live],
  }


def assign_ids(routes: list[Route], rows: list[dict[str, str]], session: str) -> list[dict[str, str]]:
  """대장에 없는 라우트에 머리글별 다음 번호를 붙여 **새 대장**을 돌려준다. 옛 번호는 그대로."""
  used: Counter[str] = Counter()
  for r in rows:
    prefix, _, num = r["API_ID"].rpartition("-")
    used[prefix] = max(used[prefix], int(num))
  known = {(r["메서드"], r["경로"]) for r in rows}
  out = list(rows)
  for rt in routes:
    if (rt.method, rt.path) in known:
      continue
    abbr = ROUTER_ABBR.get(rt.router)
    if not abbr:
      raise SystemExit(f"ROUTER_ABBR 에 '{rt.router}' 머리글이 없다 — 한 줄 더하고 다시 돌린다.")
    prefix = f"API-{abbr}"
    used[prefix] += 1
    out.append({"API_ID": f"{prefix}-{used[prefix]:02d}", "메서드": rt.method, "경로": rt.path,
                "붙인_세션": session, "상태": "사용"})
    known.add((rt.method, rt.path))
  return out


# ── 검사 · 대조 ────────────────────────────────────────────────────

def checks(routes: list[Route], cb: Codebase) -> dict[str, list]:
  key_count = Counter((r.method, r.path) for r in routes)
  registered = set(_registered_routers(cb))
  return {
    "같은_메서드_경로": [f"{m} {p} ×{n}" for (m, p), n in key_count.items() if n > 1],
    "앱에_안_붙은_라우터": sorted({r.router for r in routes if r.router not in registered}),
    "스키마_제외": [f"{r.method} {r.path}" for r in routes if not r.in_schema],
    "파트_미배정": [f"{r.method} {r.path}" for r in routes if r.part == "미배정"],
  }


def compare_openapi(routes: list[Route], spec: dict) -> dict[str, list]:
  """정적 추출 ↔ app.openapi(). 메서드 · 경로 · 경로/질의 인자 이름 · 요청 본문 모델."""
  ops: dict[tuple[str, str], dict] = {}
  for path, item in spec.get("paths", {}).items():
    for m, op in item.items():
      if m in HTTP_METHODS:
        ops[(m.upper(), path)] = op
  mine = {(r.method, r.path): r for r in routes if r.in_schema}
  diff_params: list[str] = []
  diff_body: list[str] = []
  for key in sorted(set(ops) & set(mine)):
    op, rt = ops[key], mine[key]
    theirs = sorted(p["name"] for p in op.get("parameters", []) if p.get("in") in ("path", "query"))
    ours = sorted(p.name for p in rt.params if p.kind in ("path", "query"))
    if theirs != ours:
      diff_params.append(f"{key[0]} {key[1]} — openapi {theirs} · 스캔 {ours}")
    ref = json.dumps(op.get("requestBody", {}), ensure_ascii=False)
    theirs_body = sorted(set(re.findall(r"#/components/schemas/([\w\-]+)", ref)))
    ours_body = sorted(rt.body_models)
    if theirs_body != ours_body and not (theirs_body and theirs_body[0].startswith("Body_")):
      diff_body.append(f"{key[0]} {key[1]} — openapi {theirs_body} · 스캔 {ours_body}")
  dup = Counter((r.method, r.path) for r in routes if r.in_schema)
  return {
    "openapi_오퍼레이션": [len(ops)],
    "스캔_라우트": [len(routes)],
    "openapi에만": [f"{m} {p}" for m, p in sorted(set(ops) - set(mine))],
    "스캔에만": [f"{m} {p}" for m, p in sorted(set(mine) - set(ops))],
    "스캔_중복(openapi 는 하나로 합침)": [f"{m} {p} ×{n}" for (m, p), n in dup.items() if n > 1],
    "인자_다름": diff_params,
    "본문모델_다름": diff_body,
  }


# ── 화면 잇기 (view_scan) ──────────────────────────────────────────

def _call_matches(call: str, path: str) -> bool:
  """화면 JS 의 경로 글자 ↔ 라우트 경로. JS 글자는 `?` · `${` 앞에서 잘려 있다(view_scan API_RE)."""
  if call == path:
    return True
  rx = "^" + re.sub(r"\\\{\w+(?::\w+)?\\\}", "[^/]+", re.escape(path)) + "$"
  if re.match(rx, call):
    return True
  # `/api/paper/crypto/${code}/candles` → `/api/paper/crypto/` 로 잘린 글자 — 템플릿 자리에서 시작하는 경로
  return call.endswith("/") and path.startswith(call) and path[len(call):].startswith("{")


def attach_screens(routes: list[Route], root: Path) -> dict[str, list[str]]:
  """라우트마다 부르는 화면(IA 의 view 키)을 붙이고, 어느 라우트에도 안 맞는 화면 호출을 돌려준다.

  메서드는 JS 글자에 없어서 같은 경로의 GET · POST 가 함께 잡힌다 — 「부른다」 는 과대일 수 있다.
  """
  if not (root / "public" / "app.html").exists():
    return {}
  try:
    from scripts import view_scan            # pytest · 저장소 루트에서
  except ImportError:
    import view_scan                         # python scripts/api_scan.py 로 돌릴 때
  result = view_scan.scan()
  unmatched: dict[str, set[str]] = {}
  for row in result["rows"]:
    for call in set(row["entry_apis"]) | set(row["action_apis"]):
      hit = [rt for rt in routes if _call_matches(call, rt.path)]
      for rt in hit:
        if row["key"] not in rt.screens:
          rt.screens.append(row["key"])
      if not hit:
        unmatched.setdefault(call, set()).add(row["key"])
  for rt in routes:
    rt.screens.sort()
  # 두 번째 잣대 — 메뉴 화면에 안 붙어도(로그인 · 공통 JS · 다른 화면의 헬퍼) public/ 어디엔가 글자가 있는가
  literals: set[str] = set()
  for f in sorted((root / "public").rglob("*")):
    if f.suffix in (".html", ".js"):
      literals |= set(FRONT_PATH_RE.findall(f.read_text(encoding="utf-8", errors="replace")))
  for rt in routes:
    rt.in_frontend = bool(rt.screens) or any(_call_matches(c, rt.path) for c in literals)
  return {call: sorted(v) for call, v in sorted(unmatched.items())}


# ── 출력 ───────────────────────────────────────────────────────────

REQ_ID_RE = re.compile(r"`((?:P0[12]|RFP2)-[^`]+)`")
API_ID_RE = re.compile(r"\bAPI-[A-Z]+-\d{2,}\b")


def load_requirement_map(root: Path) -> tuple[dict[str, list[str]], str]:
  """기능 설계서 부록 A(`<!-- req-api-map -->` 블록)의 표 → {API ID: [요구 ID]}.

  설계서가 요구 → API 방향의 정본이고, 이 함수는 그 표를 뒤집어 읽기만 한다.
  판이 여럿이면 가장 높은 판(`기능설계_vX.Y.md`)을 쓴다. 블록 밖의 API ID 언급은 세지 않는다.
  """
  docs = []
  for p in (root / "docs" / "설계").glob("기능설계_v*.md"):
    m = re.search(r"_v(\d+)\.(\d+)\.md$", p.name)
    if m:
      docs.append(((int(m.group(1)), int(m.group(2))), p))
  if not docs:
    return {}, ""
  path = max(docs)[1]
  text = path.read_text(encoding="utf-8")
  start, end = "<!-- req-api-map -->", "<!-- /req-api-map -->"
  if start not in text or end not in text:
    return {}, path.relative_to(root).as_posix()
  block = text.split(start, 1)[1].split(end, 1)[0]
  out: dict[str, list[str]] = {}
  for line in block.splitlines():
    if not line.startswith("|"):
      continue
    cells = line.split("|")
    req = REQ_ID_RE.search(cells[1]) if len(cells) > 2 else None
    if not req:
      continue
    for api_id in API_ID_RE.findall("|".join(cells[2:])):
      if req.group(1) not in out.setdefault(api_id, []):
        out[api_id].append(req.group(1))
  return out, path.relative_to(root).as_posix()


def scan(root: Path = ROOT) -> tuple[Codebase, list[Route], dict[str, list]]:
  cb = Codebase(root)
  routes = extract_routes(cb)
  reg = apply_registry(routes, read_registry(root))
  req_map, _src = load_requirement_map(root)
  for rt in routes:
    rt.requirements = req_map.get(rt.api_id, [])
  return cb, routes, reg


def _esc(s: str) -> str:
  return s.replace("|", "\\|").replace("\n", " ")


def _params_cell(rt: Route) -> str:
  bits: list[str] = []
  for p in rt.params:
    mark = "*" if p.required else ""
    if p.kind == "body":
      bits.append(f"본문 `{p.type}`")
    elif p.kind == "path":
      bits.append(f"`{{{p.name}}}`")
    else:
      short = {"query": "", "file": "파일 ", "form": "폼 ", "header": "헤더 ", "cookie": "쿠키 "}[p.kind]
      bits.append(f"{short}`{p.name}`{mark}")
  return " · ".join(bits) if bits else "—"


def _response_cell(rt: Route) -> str:
  if rt.response_model:
    return f"`{rt.response_model}`"
  if rt.response_kind:
    return rt.response_kind
  if rt.bridge_passthrough:
    return "다리 결과 그대로 (`source`·`as_of`)"
  if rt.return_keys:
    ks = rt.return_keys[:5]
    more = f" 외 {len(rt.return_keys) - 5}" if len(rt.return_keys) > 5 else ""
    return "{" + ", ".join(ks) + "}" + more
  return "모델 없음"


def _reach_cell(rt: Route) -> str:
  bits = [x for x in rt.reaches if x != "외부"]
  others = [h for h in rt.hosts if _host_system(h) == "외부"]
  if others:
    bits.append("외부(" + ", ".join(others[:2]) + (" …" if len(others) > 2 else "") + ")")
  if rt.route_cache_hours:
    bits.append(f"라우트 캐시 {rt.route_cache_hours}h" + (" (다리 요청 제외)" if rt.cache_after_bridge else ""))
  return " · ".join(bits) if bits else "—"


def markdown(routes: list[Route], cb: Codebase) -> str:
  out: list[str] = []
  by_router: dict[str, list[Route]] = {}
  for rt in routes:
    by_router.setdefault(rt.router, []).append(rt)
  for router, rts in by_router.items():
    out.append(f"#### `{router}` — `{rts[0].file}` · {len(rts)}개")
    out.append("")
    out.append("| API ID | 메서드 | 경로 | 인증 | 요청 | 응답 | 오류 | 닿는 곳 | 화면 | 파트(제안) | 요구 ID | 코드 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for rt in rts:
      out.append("| " + " | ".join([
        rt.api_id or "(미등록)", rt.method, f"`{rt.path}`", rt.auth, _esc(_params_cell(rt)),
        _esc(_response_cell(rt)), " · ".join(rt.errors) or "—", _esc(_reach_cell(rt)),
        ", ".join(f"`{v}`" for v in rt.screens) or ("(다른 곳)" if rt.in_frontend else "—"),
        rt.part, " · ".join(rt.requirements) or "—", f"{rt.file.rsplit('/', 1)[-1]}:{rt.line}",
      ]) + " |")
    out.append("")
  return "\n".join(out)


def markdown_models(routes: list[Route], cb: Codebase) -> str:
  # 정규 이름(모듈 포함)으로 묶는다 — 다른 파일의 같은 이름 모델이 한 줄로 합쳐지지 않게.
  used: dict[str, list[str]] = {}
  for rt in routes:
    for p in rt.params:
      if p.kind == "body":
        q = cb.resolve("app.routes." + rt.router, p.type) or p.type
        used.setdefault(q, []).append(rt.api_id or f"{rt.method} {rt.path}")
  short = Counter(q.rsplit(".", 1)[-1] for q in used)
  out = ["| 모델 | 칸 (타입 = 기본값) | 쓰는 API |", "|---|---|---|"]
  for q in sorted(used, key=lambda x: (x.rsplit(".", 1)[-1], x)):
    name = q.rsplit(".", 1)[-1]
    shown = name if short[name] == 1 else q
    fields = cb.model_fields(q)
    cell = " · ".join(f"`{f['이름']}: {f['타입']}`" + (f" = `{f['기본값']}`" if f["기본값"] else "") for f in fields)
    out.append(f"| `{shown}` | {_esc(cell) or '—'} | {', '.join(sorted(set(used[q])))} |")
  return "\n".join(out)


HTTP_MEANING = {
  "400": "요청 값이 틀림", "401": "인증 실패", "403": "권한 없음", "404": "대상 없음",
  "413": "너무 큼", "422": "검증 실패", "429": "호출 한도 초과", "500": "서버 내부 오류",
  "502": "바깥 서버 실패", "503": "의존 서비스 없음", "504": "시간 초과",
}


def markdown_overview(routes: list[Route]) -> str:
  """문서 앞부분 요약 표 넷 — 라우터별 수 · 닿는 곳 × 라우터 · 인증 없는 API · 오류 코드."""
  out: list[str] = []
  routers: dict[str, list[Route]] = {}
  for rt in routes:
    routers.setdefault(rt.router, []).append(rt)

  out += ["| 라우터 | 파일 | API | 인증 없음 | 메뉴 화면이 부름 | public/ 에 없음 | 파트(제안) |",
          "|---|---|---:|---:|---:|---:|---|"]
  for name, rts in routers.items():
    parts = Counter(r.part for r in rts)
    out.append(f"| `{name}` | `{rts[0].file}` | {len(rts)} | {sum(r.auth == '없음' for r in rts)} | "
               f"{sum(bool(r.screens) for r in rts)} | {sum(not r.in_frontend for r in rts)} | "
               + " · ".join(f"{k} {v}" for k, v in parts.most_common()) + " |")
  out.append(f"| **합계** | {len(routers)}개 | **{len(routes)}** | **{sum(r.auth == '없음' for r in routes)}** | "
             f"**{sum(bool(r.screens) for r in routes)}** | **{sum(not r.in_frontend for r in routes)}** | |")
  out.append("")

  used = [s for s in SYSTEM_ORDER if any(s in r.reaches for r in routes)]
  out += ["| 라우터 | " + " | ".join(used) + " |", "|---|" + "---:|" * len(used)]
  for name, rts in routers.items():
    out.append(f"| `{name}` | " + " | ".join(str(sum(s in r.reaches for r in rts) or "·") for s in used) + " |")
  out.append("| **합계** | " + " | ".join(f"**{sum(s in r.reaches for r in routes)}**" for s in used) + " |")
  out.append("")

  out += ["| API ID | 메서드 | 경로 | 닿는 곳 | 화면 |", "|---|---|---|---|---|"]
  for rt in routes:
    if rt.auth == "없음":
      out.append(f"| {rt.api_id} | {rt.method} | `{rt.path}` | {_esc(_reach_cell(rt))} | "
                 + (", ".join(f"`{v}`" for v in rt.screens) or ("(다른 곳)" if rt.in_frontend else "—")) + " |")
  out.append("")

  codes: dict[str, list[str]] = {}
  for rt in routes:
    for e in rt.errors:
      codes.setdefault(e, []).append(rt.api_id)
  out += ["| 코드 | 뜻 | 본문에 적힌 API 수 | API ID |", "|---|---|---:|---|"]
  for code in sorted(codes, key=lambda c: (c[:3], c)):
    ids = codes[code]
    shown = ", ".join(ids[:6]) + (f" 외 {len(ids) - 6}" if len(ids) > 6 else "")
    out.append(f"| `{code}` | {HTTP_MEANING.get(code[:3], '')} | {len(ids)} | {shown} |")
  return "\n".join(out)


def summary(routes: list[Route], cb: Codebase, reg: dict[str, list], chk: dict[str, list],
            unmatched: dict[str, list[str]]) -> None:
  print(f"라우트 {len(routes)}개 · 라우터 {len({r.router for r in routes})}개 · 앱 모듈 {len(cb.trees)}개 (import 없음)")
  print("메서드   ", dict(Counter(r.method for r in routes).most_common()))
  print("인증     ", dict(Counter(r.auth for r in routes).most_common()))
  print("파트     ", dict(Counter(r.part for r in routes).most_common()))
  sys_count = Counter(s for r in routes for s in r.reaches)
  print("닿는 곳  ", {s: sys_count[s] for s in SYSTEM_ORDER if sys_count[s]})
  print("응답모델 ", sum(1 for r in routes if r.response_model), "/", len(routes),
        "· 다리 결과 그대로", sum(1 for r in routes if r.bridge_passthrough),
        "· 라우트 캐시", sum(1 for r in routes if r.route_cache_hours))
  print("오류코드 ", dict(Counter(e for r in routes for e in r.errors).most_common()))
  print("화면     ", "메뉴 화면이 부르는 API", sum(1 for r in routes if r.screens), "/", len(routes),
        "· public/ 어디에도 글자가 없는 API", sum(1 for r in routes if not r.in_frontend))
  print("요구     ", "요구 ID 가 붙은 API", sum(1 for r in routes if r.requirements), "/", len(routes),
        "(기능 설계서 부록 A)")
  print()
  print("── 증권사 관문에 닿는 라우트 (실거래 차단 ADR-0001 · 관문은 factory.get_broker_client) ──")
  for r in routes:
    if "증권사" in r.reaches:
      print(f"  {r.api_id or '(미등록)'} {r.method} {r.path} · 인증 {r.auth}" + (" · 주문" if "주문" in r.reaches else ""))
  print("── 수집 DB 다리에 닿는 라우트 (DF-08) ──")
  for r in routes:
    if "수집DB" in r.reaches:
      extra = " · 응답에 source·as_of" if r.bridge_passthrough else " · 응답 모양은 코드 확인"
      cache = ""
      if r.route_cache_hours:
        cache = (f" · 라우트 캐시 {r.route_cache_hours}h 는 옛 경로만(다리 요청 제외 · DF-17)" if r.cache_after_bridge
                 else f" · ⚠️ 라우트 캐시 {r.route_cache_hours}h")
      print(f"  {r.api_id or '(미등록)'} {r.method} {r.path}{extra}{cache}")
  print()
  print("── 화면이 부르는데 맞는 라우트가 없는 경로 ──")
  for call, views in unmatched.items():
    print(f"  {call} ← {', '.join(views)}")
  print()
  for k, v in {**reg, **chk}.items():
    print(f"{'✅' if not v else '⚠️'} {k}: {len(v)}")
    for x in v[:20]:
      print("     ", x)


DOC_BLOCKS = ("overview", "routes", "models")


def fill_doc(text: str, blocks: dict[str, str]) -> str:
  """문서 안 `<!-- api_scan:이름 -->` … `<!-- /api_scan:이름 -->` 사이를 새 출력으로 바꾼다.

  표시 밖의 사람이 쓴 글은 건드리지 않는다. 줄 끝은 문서가 쓰던 것(CRLF · LF)을 따른다 —
  작업 트리는 CRLF 인데 LF 를 섞으면 `git ls-files --eol` 이 w/mixed 가 된다(S62).
  """
  nl = "\r\n" if "\r\n" in text else "\n"
  for name, body in blocks.items():
    start, end = f"<!-- api_scan:{name} -->", f"<!-- /api_scan:{name} -->"
    if text.count(start) != 1 or text.count(end) != 1:
      raise SystemExit(f"문서에 {start} · {end} 표시가 한 쌍 있어야 한다")
    head, rest = text.split(start, 1)
    _old, tail = rest.split(end, 1)
    text = head + start + nl + body.replace("\n", nl) + nl + end + tail
  return text


def main(argv: list[str] | None = None) -> int:
  # git bash(mintty)에서는 표준출력이 cp949 가 된다 → ✅ · ⚠️ · — 한 글자에서 죽는다 (DF-11).
  for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
      stream.reconfigure(encoding="utf-8")
  ap = argparse.ArgumentParser(description="API 명세 실측 추출기 (앱을 import 하지 않는다)")
  ap.add_argument("--md", action="store_true", help="라우터별 마크다운 표")
  ap.add_argument("--models", action="store_true", help="요청 본문 모델 표")
  ap.add_argument("--overview", action="store_true", help="요약 표 넷(라우터 · 닿는 곳 · 인증 없음 · 오류 코드)")
  ap.add_argument("--json", action="store_true", help="JSON")
  ap.add_argument("--openapi", metavar="파일", help="app.openapi() JSON 과 대조")
  ap.add_argument("--assign", metavar="세션", help="대장에 없는 라우트에 새 ID 를 붙여 대장에 쓴다")
  ap.add_argument("--doc", metavar="문서", help="문서 안 api_scan 표시 사이를 새 출력으로 채운다")
  ap.add_argument("--check", action="store_true", help="--doc 과 함께: 고치지 않고 어긋나면 종료코드 1")
  args = ap.parse_args(argv)

  cb, routes, reg = scan(ROOT)
  if args.assign:
    rows = assign_ids(routes, read_registry(ROOT), args.assign)
    write_registry(ROOT, rows)
    reg = apply_registry(routes, rows)
    print(f"대장 {ROOT / ID_REGISTRY_REL} · {len(rows)}줄")
  chk = checks(routes, cb)
  unmatched = attach_screens(routes, ROOT)
  if args.doc:
    doc = Path(args.doc)
    old = doc.read_bytes().decode("utf-8")
    new = fill_doc(old, {"overview": markdown_overview(routes), "routes": markdown(routes, cb),
                         "models": markdown_models(routes, cb)})
    if args.check:
      print("✅ 문서가 코드와 같다" if new == old else "⚠️ 문서가 코드보다 뒤처졌다 — --doc 로 다시 채운다")
      return 0 if new == old else 1
    doc.write_bytes(new.encode("utf-8"))
    print(f"채움: {doc} · 표시 {len(DOC_BLOCKS)}곳")
    return 0
  if args.json:
    print(json.dumps({"routes": [asdict(r) for r in routes], "대장": reg, "검사": chk,
                      "화면_호출_맞는_라우트_없음": unmatched}, ensure_ascii=False, indent=1))
  elif args.md:
    print(markdown(routes, cb))
  elif args.models:
    print(markdown_models(routes, cb))
  elif args.overview:
    print(markdown_overview(routes))
  elif args.openapi:
    spec = json.loads(Path(args.openapi).read_text(encoding="utf-8"))
    for k, v in compare_openapi(routes, spec).items():
      print(f"{k}: {v if k.endswith(('오퍼레이션', '라우트')) else len(v)}")
      if not k.endswith(("오퍼레이션", "라우트")):
        for x in v:
          print("     ", x)
  else:
    summary(routes, cb, reg, chk, unmatched)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
