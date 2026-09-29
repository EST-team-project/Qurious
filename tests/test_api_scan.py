"""API 명세 스캐너 시험 (TC-AP) — API 명세서 v0.1 의 표가 믿을 만한가.

무엇을 지키는가 —
API 명세서의 표는 `scripts/api_scan.py` 출력을 붙인 것이다. 그러니 문서가 믿을 만하려면
스캐너가 ① 라우트를 하나도 놓치지 않고 ② 다시 돌려도 같은 표를 내고 ③ ID 가 밀리지 않고
④ 「닿는 곳」 판정 규칙(인증 이름표 · 다리 `as_of` · 증권사 관문 · 주문)이 코드 모양대로 서야 한다.

실제 저장소에는 **늘 참이어야 하는 성질만** 건다(데코레이터 수 = 추출 수 · 중복 0 · 붙지 않은
라우터 0). 「인증 없는 라우트가 33개」 같은 지금의 사실은 걸지 않는다 — 팀원이 라우트를
고치면 그건 좋은 일인데 시험이 깨진다. 판정 규칙은 합성 저장소(tmp_path)로 잰다.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from scripts import api_scan

ROOT = Path(__file__).resolve().parents[1]

# ── 합성 저장소 ────────────────────────────────────────────────────

ROUTES_SRC = '''
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from app.lib.session import get_current_user
from app.lib.jwt_auth import require_roles
from app.database.postgres import get_pg_session
from app.services.stock import get_candles
from app.services.brokers.factory import get_broker_client

router = APIRouter(prefix="/api")


class OrderBody(BaseModel):
    symbol: str
    qty: int = 1


def _require_admin(user=Depends(get_current_user)):
    if "admin" not in user.get("roles", []):
        raise HTTPException(403, "no")
    return user


@router.get("/candles")
async def candles(symbol: str = Query(...), period: str = "1y"):
    data = await get_candles(symbol)
    return data


@router.get("/summary")
async def summary(symbol: str):
    data = await get_candles(symbol)
    return {"n": len(data["candles"])}


@router.get("/broker/price")
async def price(user=Depends(get_current_user)):
    client = get_broker_client("kis")
    return await client.price()


@router.post("/broker/order/{account}")
async def order(account: str, body: OrderBody | None = None,
                user=Depends(get_current_user), db=Depends(get_pg_session)):
    client = get_broker_client("kis")
    if body is None:
        raise HTTPException(status_code=422, detail="body")
    return await client.place_order()


@router.delete("/admin/reset")
async def reset(user=Depends(_require_admin)):
    return {"ok": True}


@router.delete("/sessions")
async def all_sessions(user=Depends(require_roles("admin", "user"))):
    return {"ok": True}
'''

FILES = {
  "app/__init__.py": "",
  "app/main.py": "from fastapi import FastAPI\nfrom app.routes import stocks\napp = FastAPI()\napp.include_router(stocks.router)\n",
  "app/routes/__init__.py": "",
  "app/routes/stocks.py": ROUTES_SRC,
  "app/lib/__init__.py": "",
  "app/lib/session.py": "async def get_current_user():\n    return {}\n",
  "app/lib/jwt_auth.py": (
    "from fastapi import Depends\n"
    "async def get_current_user_any():\n    return {}\n"
    "def require_roles(*roles):\n"
    "    async def _check(user=Depends(get_current_user_any)):\n        return user\n"
    "    return _check\n"
  ),
  "app/database/__init__.py": "",
  "app/database/postgres.py": "async def get_pg_session():\n    yield None\n",
  "app/services/__init__.py": "",
  "app/services/collector_db.py": (
    "import asyncio\n"
    "def read_daily_candles(symbol):\n"
    "    return {'candles': [], 'source': 'collector', 'as_of': '2026-09-23'}\n"
    "async def get_daily_candles(symbol):\n"
    "    return await asyncio.to_thread(read_daily_candles, symbol)\n"
  ),
  "app/services/stock.py": (
    "from app.services import collector_db\n"
    "YAHOO = 'https://query2.finance.yahoo.com/v8/finance/chart/'\n"
    "async def _yahoo_chart(symbol):\n    return YAHOO + symbol\n"
    "async def get_candles(symbol):\n"
    "    local = await collector_db.get_daily_candles(symbol)\n"
    "    if local is not None:\n        return local\n"
    "    return {'candles': await _yahoo_chart(symbol)}\n"
  ),
  "app/services/brokers/__init__.py": "",
  "app/services/brokers/factory.py": (
    "REAL_URL = 'https://openapi.broker.example.com'\n"
    "class Client:\n"
    "    async def place_order(self):\n        return REAL_URL\n"
    "    async def price(self):\n        return 1\n"
    "    async def resend(self):\n        return await self.place_order()\n"
    "def get_broker_client(broker):\n    return Client()\n"
  ),
}


def _repo(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
  for rel, src in {**FILES, **(extra or {})}.items():
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
  return tmp_path


def _by_path(routes: list[api_scan.Route]) -> dict[str, api_scan.Route]:
  return {f"{r.method} {r.path}": r for r in routes}


# ── 실제 저장소 — 늘 참이어야 하는 성질 ───────────────────────────────

def test_ap01_스캐너는_앱을_import_하지_않는다():
  """서비스 5개가 없어도 돈다 — 자식 프로세스에 app 모듈이 하나도 올라오지 않아야 한다."""
  code = (
    "import sys; sys.path.insert(0, '.')\n"
    "from scripts import api_scan\n"
    "api_scan.scan()\n"
    "print(sorted(m for m in sys.modules if m == 'app' or m.startswith('app.')))\n"
  )
  out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", check=True)
  assert out.stdout.strip() == "[]"


def test_ap02_데코레이터를_하나도_놓치지_않는다():
  """줄 단위로 센 `@router.<메서드>(` 수 = AST 로 뽑은 라우트 수. 라우트가 늘어도 참이다."""
  pattern = re.compile(r"^@router\.(get|post|put|delete|patch)\(", re.M)
  by_lines = sum(len(pattern.findall(p.read_text(encoding="utf-8")))
                 for p in (ROOT / "app" / "routes").glob("*.py"))
  _cb, routes, _reg = api_scan.scan(ROOT)
  assert by_lines == len(routes) > 0


def test_ap03_다시_돌려도_같은_표가_나온다():
  """문서가 약속하는 것 — 손으로 옮긴 숫자가 없고, 의심스러우면 다시 돌리면 된다."""
  first = api_scan.scan(ROOT)
  second = api_scan.scan(ROOT)
  assert api_scan.markdown(first[1], first[0]) == api_scan.markdown(second[1], second[0])
  assert api_scan.markdown_models(first[1], first[0]) == api_scan.markdown_models(second[1], second[0])


def test_ap04_같은_메서드_경로가_없고_붙지_않은_라우터가_없다():
  """FastAPI 는 같은 메서드·경로를 두 번 등록해도 말없이 앞의 것만 쓴다 — 그건 결함이다."""
  cb, routes, _reg = api_scan.scan(ROOT)
  chk = api_scan.checks(routes, cb)
  assert chk["같은_메서드_경로"] == []
  assert chk["앱에_안_붙은_라우터"] == []


# ── 판정 규칙 — 합성 저장소 ─────────────────────────────────────────

def test_ap05_인증_이름표(tmp_path):
  _cb, routes, _reg = api_scan.scan(_repo(tmp_path))
  r = _by_path(routes)
  assert r["GET /api/candles"].auth == "없음"
  assert r["GET /api/broker/price"].auth == "세션"
  assert r["DELETE /api/admin/reset"].auth == "세션 + 관리자"       # 지역 의존성 안으로 들어간다
  assert r["DELETE /api/sessions"].auth == "세션·JWT + 역할(admin·user)"
  assert r["POST /api/broker/order/{account}"].uses_db_session is True


def test_ap06_다리_결과를_그대로_돌려줄_때만_as_of_가_실린다(tmp_path):
  """`asyncio.to_thread(함수, …)` 로 넘긴 것도 사슬로 잇는다. 바꿔 돌려주면 싣지 않는다."""
  _cb, routes, _reg = api_scan.scan(_repo(tmp_path))
  r = _by_path(routes)
  assert r["GET /api/candles"].bridge_passthrough is True
  assert r["GET /api/summary"].bridge_passthrough is False
  assert "수집DB" in r["GET /api/summary"].reaches        # 닿기는 닿는다
  assert "야후" in r["GET /api/candles"].reaches          # 가능한 길의 합집합


def test_ap07_증권사_관문과_주문을_가른다(tmp_path):
  """관문 함수가 가리키는 클래스 몸통의 `place_order` 로는 「주문」 이 되지 않는다."""
  _cb, routes, _reg = api_scan.scan(_repo(tmp_path))
  r = _by_path(routes)
  assert "증권사" in r["GET /api/broker/price"].reaches
  assert "주문" not in r["GET /api/broker/price"].reaches
  assert "주문" in r["POST /api/broker/order/{account}"].reaches
  assert "openapi.broker.example.com" in r["GET /api/broker/price"].hosts


def test_ap08_선택형_본문_모델과_인자_종류(tmp_path):
  _cb, routes, _reg = api_scan.scan(_repo(tmp_path))
  r = _by_path(routes)
  kinds = {p.name: (p.kind, p.required) for p in r["POST /api/broker/order/{account}"].params}
  assert kinds == {"account": ("path", True), "body": ("body", False)}
  assert r["POST /api/broker/order/{account}"].body_models == ["OrderBody"]
  assert r["POST /api/broker/order/{account}"].errors == ["422"]
  q = {p.name: (p.kind, p.required) for p in r["GET /api/candles"].params}
  assert q == {"symbol": ("query", True), "period": ("query", False)}


def test_ap09_ID_는_라우트가_끼어들어도_밀리지_않는다(tmp_path):
  """RTM §2.2 의 교훈 — 순번은 하나가 끼면 뒤가 전부 밀린다. 대장은 옛 번호를 그대로 둔다."""
  root = _repo(tmp_path)
  _cb, routes, _reg = api_scan.scan(root)
  api_scan.write_registry(root, api_scan.assign_ids(routes, [], "S63"))
  before = {f'{r["메서드"]} {r["경로"]}': r["API_ID"] for r in api_scan.read_registry(root)}

  src = ROUTES_SRC.replace('@router.get("/candles")',
                           '@router.get("/new-first")\nasync def new_first():\n    return {}\n\n\n@router.get("/candles")')
  (root / "app/routes/stocks.py").write_text(src, encoding="utf-8")
  _cb, routes2, reg2 = api_scan.scan(root)
  assert reg2["미등록"] == ["GET /api/new-first"]
  api_scan.write_registry(root, api_scan.assign_ids(routes2, api_scan.read_registry(root), "S64"))
  after = {f'{r["메서드"]} {r["경로"]}': r["API_ID"] for r in api_scan.read_registry(root)}

  assert {k: after[k] for k in before} == before
  assert after["GET /api/new-first"] == f"API-STK-{len(before) + 1:02d}"


def test_ap11_화면_JS_경로를_라우트에_맞추는_규칙():
  """JS 글자는 `?` · `${` 앞에서 잘린다(view_scan). 잘린 자리가 템플릿 자리일 때만 잇는다."""
  m = api_scan._call_matches
  assert m("/api/stocks/quote", "/api/stocks/quote")
  assert m("/api/portfolio/005930.KS", "/api/portfolio/{symbol}")
  assert m("/api/paper/crypto/", "/api/paper/crypto/{code}/candles")        # `${code}` 앞에서 잘림
  assert not m("/api/stocks/", "/api/stocks/quote")                         # 템플릿 자리가 아니다
  assert not m("/api/stocks/quote", "/api/stocks/quote/extra")


def test_ap12_다른_파일의_같은_이름_모델을_합치지_않는다(tmp_path):
  """모델 표는 이름으로 묶으면 두 `OrderBody` 가 한 줄이 되어 칸이 틀린다 — 정규 이름으로 묶는다."""
  paper = (
    "from fastapi import APIRouter\nfrom pydantic import BaseModel\n"
    "router = APIRouter(prefix='/api/paper')\n"
    "class OrderBody(BaseModel):\n    coin: str\n"
    "@router.post('/orders')\nasync def order(body: OrderBody):\n    return {}\n"
  )
  main = FILES["app/main.py"].replace("from app.routes import stocks",
                                      "from app.routes import stocks, paper") + "app.include_router(paper.router)\n"
  cb, routes, _reg = api_scan.scan(_repo(tmp_path, {"app/routes/paper.py": paper, "app/main.py": main}))
  table = api_scan.markdown_models(routes, cb)
  assert "`app.routes.paper.OrderBody` | `coin: str`" in table
  assert "`app.routes.stocks.OrderBody` | `symbol: str`" in table


def test_ap13_요구_ID_는_기능_설계서_부록_블록에서만_읽는다(tmp_path):
  """설계서가 요구 → API 의 정본이다. 블록 밖 언급 · 낮은 판은 읽지 않는다."""
  root = _repo(tmp_path)
  _cb, routes, _reg = api_scan.scan(root)
  api_scan.write_registry(root, api_scan.assign_ids(routes, [], "S63"))
  ids = {f'{r["메서드"]} {r["경로"]}': r["API_ID"] for r in api_scan.read_registry(root)}
  candles, price = ids["GET /api/candles"], ids["GET /api/broker/price"]
  design = root / "docs" / "설계"
  design.mkdir(parents=True)
  (design / "기능설계_v0.1.md").write_text(
    f"<!-- req-api-map -->\n| `P01-①-2` | {price} |\n<!-- /req-api-map -->\n", encoding="utf-8")
  (design / "기능설계_v0.2.md").write_text(
    f"본문에서 {price} 를 말한다 — 블록 밖이라 세지 않는다.\n"
    "<!-- req-api-map -->\n"
    "| 요구 | API |\n|---|---|\n"
    f"| `P01-①-2` 가격·거래량 | {candles} · (새) `GET /api/data/status` |\n"
    f"| `P02-④-1` 동일 조건 | {candles} |\n"
    "<!-- /req-api-map -->\n", encoding="utf-8")
  _cb, routes, _reg = api_scan.scan(root)
  r = _by_path(routes)
  assert r["GET /api/candles"].requirements == ["P01-①-2", "P02-④-1"]
  assert r["GET /api/broker/price"].requirements == []        # v0.1 은 낮은 판 · v0.2 블록 밖 언급


def test_ap14_다리_요청을_캐시보다_먼저_가르면_라우트_캐시는_옛_경로_몫이다(tmp_path):
  """DF-17 — `collector_db.handles(...)` 로 다리 요청을 **캐시보다 먼저** 돌려보내는 라우트는 경고하지 않는다.
  캐시를 먼저 보고 나서 가르면 옛 값이 이미 나간 뒤라 그대로 경고한다."""
  src = ROUTES_SRC + '''
from app.services import collector_db
from app.services.data_cache import cache_get


@router.get("/cached")
async def cached(symbol: str):
    hit = await cache_get("k", max_age_hours=6)
    return hit or await get_candles(symbol)


@router.get("/cached-bridge-first")
async def cached_bridge_first(symbol: str):
    if collector_db.handles(symbol):
        return await get_candles(symbol)
    hit = await cache_get("k", max_age_hours=6)
    return hit or await get_candles(symbol)


@router.get("/cached-bridge-late")
async def cached_bridge_late(symbol: str):
    hit = await cache_get("k", max_age_hours=6)
    if hit is None and collector_db.handles(symbol):
        return await get_candles(symbol)
    return hit
'''
  extra = {
    "app/routes/stocks.py": src,
    "app/services/data_cache.py": "async def cache_get(key, max_age_hours=24):\n    return None\n",
  }
  _cb, routes, _reg = api_scan.scan(_repo(tmp_path, extra))
  r = _by_path(routes)
  plain, first, late = r["GET /api/cached"], r["GET /api/cached-bridge-first"], r["GET /api/cached-bridge-late"]
  assert plain.route_cache_hours == first.route_cache_hours == late.route_cache_hours == "6"
  assert (plain.cache_after_bridge, first.cache_after_bridge, late.cache_after_bridge) == (False, True, False)
  assert "라우트 캐시 6h (다리 요청 제외)" in api_scan._reach_cell(first)
  assert "다리 요청 제외" not in api_scan._reach_cell(late)


def test_ap10_openapi_대조가_빠진_것과_인자_차이를_잡는다(tmp_path):
  _cb, routes, _reg = api_scan.scan(_repo(tmp_path))
  spec = {"paths": {
    "/api/candles": {"get": {"parameters": [{"name": "symbol", "in": "query"}]}},
    "/api/ghost": {"get": {}},
  }}
  res = api_scan.compare_openapi(routes, spec)
  assert res["openapi에만"] == ["GET /api/ghost"]
  assert "GET /api/summary" in res["스캔에만"]
  assert len(res["인자_다름"]) == 1 and "period" in res["인자_다름"][0]
  json.dumps(res, ensure_ascii=False)   # --json 으로도 나가야 한다
