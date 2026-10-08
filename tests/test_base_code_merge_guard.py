"""강사님 기초 코드 반영 지킴이 — 3-way 병합이 충돌 표시 없이 들여오는 위험을 막는다 (TC-BM).

Qurious 는 강사님 lumina-invest 사본에서 출발했고, 강사님이 기초 코드를 고칠 때마다 3-way 로 받는다
(지난 반영 커밋이 기준). 그런데 위험한 것은 충돌이 아니라 **충돌 없이 들어오는 줄**이다.

1. 2026-09-15 에 걷어낸 AWS 코드(SageMaker 배치 점수 · Secrets Manager · boto3)가 import 한 줄로 되살아난다.
   강사님 9478811 의 `auto_trade.py` 맨 위 `from app.services.quant_ai_scores import …` 가 그랬다 —
   지운 모듈이라 합치는 순간 앱 · Celery 가 ImportError 로 뜨지 않는다(자동매매 라우트가 이 모듈을 부른다).
2. 그래서 반영할 때마다 이 파일을 먼저 돌린다. 기준은 「AWS 를 쓰지 않는다」 는 팀 방침(계획서 · AWS 는 비용 합의 뒤)이지
   특정 함수 이름이 아니다 — 주석은 세지 않고 실제 import 줄만 본다.
"""
import ast
import asyncio
import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _code_names(module) -> set[str]:
    """모듈이 실제로 import 하거나 부르는 이름 — 설명(독스트링 · 주석)에 적은 글자는 세지 않는다."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and " " not in node.value:
            names.add(node.value)   # boto3.client("secretsmanager") 같은 서비스 이름
    return names

# 09-15 에 걷어낸 AWS 쪽 모듈 · 패키지. 다시 쓰기로 정하면(팀 비용 합의) 이 목록을 줄인다.
AWS_IMPORTS = re.compile(
    r"^\s*(from|import)\s+(boto3|botocore|sagemaker|app\.services\.quant_ai_scores|app\.services\.aws_\w+)\b"
)


def _app_python_files():
    for path in (ROOT / "app").rglob("*.py"):
        if "__pycache__" not in path.parts:
            yield path


def test_앱_코드가_걷어낸_AWS_모듈을_import_하지_않는다():
    """함수 안의 지연 import(`import boto3` 를 함수 몸통에 둔 강사님 방식)도 줄 단위로 잡는다."""
    found = []
    for path in _app_python_files():
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if AWS_IMPORTS.match(line):
                found.append(f"{path.relative_to(ROOT).as_posix()}:{no}: {line.strip()}")
    assert not found, "걷어낸 AWS import 가 되살아났다:\n" + "\n".join(found)


def test_지운_SageMaker_점수_모듈은_없다():
    assert not (ROOT / "app" / "services" / "quant_ai_scores.py").exists()


def test_자동매매_모듈이_뜨고_배치_ML_점수는_늘_비어_있다():
    """`ml_scores_by_symbol()` 은 SageMaker 배치 점수를 읽던 함수다 — 우리 판은 늘 빈 dict(캔들 Ridge 점수만 쓴다)."""
    from app.services import auto_trade

    assert not {n for n in _code_names(auto_trade) if "quant_ai_scores" in n}
    assert asyncio.run(auto_trade.ml_scores_by_symbol()) == {}


def test_KIS_자격증명_모듈에_Secrets_Manager_갈래가_없다():
    """강사님 판은 Secrets Manager → .env 순으로 서버 계좌 하나를 읽는다. 우리 판은 사용자마다 자기 키(2026-10-03 결정)."""
    from app.services import kis_credentials

    names = _code_names(kis_credentials)
    for banned in ("boto3", "secretsmanager", "get_secret_value"):
        assert banned not in names, f"kis_credentials 에 {banned} 가 남아 있다"


# ── 2026-10-08 th06 e815be3 반영 — 「받지 않음」 으로 정한 값 · 우리 판으로 둔 곳 ─────────────
# 강사님 23커밋(9478811 → e815be3) 가운데 다른 주담당 몫인 운용 값 넷은 설정 이름 · 구조만 받고 값은 우리 것으로 둔다
# (사용자 10-08 — 받을지는 팀 이슈로). 3-way 는 이 값들을 충돌 없이 강사님 값으로 바꾸므로, 다음 반영 때도 여기서 걸린다.
# 이름은 지키고 값만 바꾼 까닭: 강사님 코드 여러 곳(헬스 · 빠른 시작 · 모니터 · 예약)이 같은 설정 이름을 읽는다.

OUR_UNIVERSE = frozenset({
    "005930.KS", "000660.KS", "042700.KS", "009150.KS", "035420.KS", "035720.KS", "018260.KS", "259960.KS",
    "036570.KS", "251270.KS", "005380.KS", "000270.KS", "051910.KS", "006400.KS", "373220.KS", "010950.KS",
    "207940.KS", "068270.KS", "105560.KS", "055550.KS", "086790.KS", "005490.KS", "010130.KS", "034730.KS",
    "003550.KS", "015760.KS", "017670.KS", "030200.KS", "097950.KS", "090430.KS", "352820.KS",
})


def _default(name: str):
    """설정의 코드 기본값 — 이 PC 의 .env 와 상관없이 「코드가 무엇을 들여왔나」 를 본다."""
    from app.config import settings

    return type(settings).model_fields[name].default


def test_자동매매_주기는_600초다():
    """강사님 10-07: 5분 → 3분(`QUANT_CYCLE_SEC=180`). 우리 판은 이름만 받고 600초(10분) 그대로 — 예약도 그 값을 따른다."""
    from app.celery_app import celery_app
    from app.config import settings

    assert _default("QUANT_CYCLE_SEC") == 600
    entry = celery_app.conf.beat_schedule["quant-auto-trade-cycle"]
    assert entry["task"] == "quant.auto_trade_cycle" and entry["schedule"] == float(settings.QUANT_CYCLE_SEC)


def test_유니버스는_우리_31종목이다():
    """강사님 10-07: 3섹터(반도체 · IT · K뷰티) 31종목으로 22개를 바꿨다 — 스크리닝 · 자동매매 · 리밸런싱이 같이 움직여 팀이 정한다."""
    from app.services.stock import QUANT_SECTORS, QUANT_STOCKS

    assert {s["symbol"] for s in QUANT_STOCKS} == OUR_UNIVERSE
    # 섹터 목록은 유니버스에서 만든다 — 강사님 판은 셋을 글자로 적어 두어 우리 목록과 어긋난다
    assert set(QUANT_SECTORS) == {s["sector"] for s in QUANT_STOCKS}


def test_원클릭_1회_투자금은_30만_원이다():
    """강사님 10-07: 30만 → 50만 원(빠른 시작 · 배치 둘 다)."""
    from app.services import kis_quickstart

    assert kis_quickstart.TESTBED_DEFAULTS["quant_per_trade_budget"] == 300_000.0
    assert _default("KIS_PAPER_BATCH_PER_TRADE_BUDGET") == 300_000


def test_정합성_점검은_기본으로_꺼져_요약을_남기지_않는다(monkeypatch):
    """강사님 판은 켜져 있고, 같은 환경 모든 사용자의 체결을 합산한 요약이 로그인한 모두의 상태 응답(`reconcile`)에 실린다.
    끄면 점검이 캐시를 남기지 않으므로 상태 · KIS 모니터 응답의 `reconcile` 이 늘 비어 있다(라우트는 강사님 판 그대로)."""
    from unittest.mock import AsyncMock

    from app.config import settings
    from app.services import reconciliation

    assert _default("RECONCILE_ENABLED") is False
    monkeypatch.setattr(settings, "RECONCILE_ENABLED", _default("RECONCILE_ENABLED"))
    saved = AsyncMock()
    monkeypatch.setattr(reconciliation, "cache_set", saved)
    report = asyncio.run(reconciliation.run_reconciliation(None))
    assert report["summary"].get("note") == "RECONCILE_ENABLED=false"
    saved.assert_not_awaited()


def test_채팅_기본_모델은_llama3_1_이다():
    """강사님은 이틀 사이 qwen2.5 1.5b → 7b → 3b. 우리 판은 W8 평가 기준선 모델을 둔다(S76 · 10-08).
    compose 의 기본값은 강사님 판 그대로 받는다(S76 결정) — 이 PC 는 .env 의 COMPOSE_LLM_MODEL 로 덮는다."""
    assert _default("LLM_MODEL") == "llama3.1"


def test_compose_기본_채팅_모델은_Apache_2_0_인_1_5b_다():
    """강사님 10-07 판 compose 는 컨테이너 Ollama 기본 모델을 qwen2.5:3b 로 바꿨다 — Qwen RESEARCH LICENSE
    (「FOR NON-COMMERCIAL PURPOSES ONLY」 · 연구 또는 평가 목적만 · 2026-10-08 모델 카드 LICENSE 원문 확인).
    `.env` 에 COMPOSE_LLM_MODEL 을 안 둔 사람의 도커가 이 값을 받으므로 기본값은 Apache-2.0 인 1.5b 로 둔다(사용자 10-08)."""
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    defaults = re.findall(r"COMPOSE_LLM_MODEL:-([\w.:-]+)\}", text)
    assert defaults and set(defaults) == {"qwen2.5:1.5b"}, defaults


def test_답을_만드는_호출은_설정의_길이를_쓴다(monkeypatch):
    """강사님 10-07 판은 에이전트 답 · 그래프 RAG · RAG 체인의 출력 상한을 256토큰 · 문맥 2048 로 줄였다(세 파일에 글자로).
    이 PC 표본 3문항이 모두 문장 중간에 잘리고 끝 고지가 빠져(10-08 측정 · 자연 길이 454 ~ 684토큰) 값을 설정 한 곳에 둔다.
    판단(JSON 한 줄) 노드는 강사님 256 그대로라 에이전트 파일의 256 은 꼭 한 번만 남는다."""
    from app.config import settings
    from app.lib import llm_limits

    assert _default("LLM_ANSWER_NUM_PREDICT") >= 1024 and _default("LLM_NUM_CTX") == 0
    monkeypatch.setattr(settings, "LLM_ANSWER_NUM_PREDICT", 1024)
    monkeypatch.setattr(settings, "LLM_NUM_CTX", 0)
    assert llm_limits.answer_options() == {"num_predict": 1024}   # 0 이면 문맥 창을 넣지 않는다(Ollama 기본)
    monkeypatch.setattr(settings, "LLM_NUM_CTX", 4096)
    assert llm_limits.answer_options() == {"num_predict": 1024, "num_ctx": 4096}
    texts = {rel: (ROOT / rel).read_text(encoding="utf-8")
             for rel in ("app/services/langgraph_agent.py", "app/services/graph_rag.py", "app/services/rag_pipeline.py")}
    for rel, src in texts.items():
        assert "**answer_options()" in src, f"{rel} 가 설정의 답 길이를 읽지 않는다"
    assert len(re.findall(r"num_predict[\"']?\s*[:=]\s*256\b", texts["app/services/langgraph_agent.py"])) == 1
    for rel in ("app/services/graph_rag.py", "app/services/rag_pipeline.py"):
        assert not re.search(r"num_predict\s*=\s*\d", texts[rel]), f"{rel} 에 답 길이가 글자로 박혔다"


ENV_EXAMPLE_OVERRIDES = re.compile(r"^\s*(KIS_PAPER_BATCH_\w+|QUANT_CYCLE_SEC|RECONCILE_ENABLED)\s*=", re.M)


def test_env_example_이_우리_값을_덮어쓰지_않는다():
    """`.env.example` 을 복사해 `.env` 를 만들면 거기 적힌 값이 코드 기본값을 덮어쓴다 — 강사님 판의 배치 칸 · 180초 ·
    정합성 켬을 싣지 않는다(배치는 서버 계좌 하나로 도는 기능이라 사용자마다 키를 쓰는 우리 원칙(ADR-0004)과도 어긋난다)."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    found = [m.group(1) for m in ENV_EXAMPLE_OVERRIDES.finditer(text)]
    assert not found, f".env.example 이 코드 기본값을 덮어쓰는 칸을 싣는다: {found}"


def test_시세는_KIS_설정이어도_수집DB가_먼저다(monkeypatch):
    """강사님 판은 국내 일봉을 KIS(st 게이트웨이) 먼저 읽는다. 우리 판은 수집 DB(수정주가 · DF-08) → KIS → Yahoo."""
    from unittest.mock import AsyncMock

    from app.services import collector_db, stock
    from app.services import kis_market_data as kmd

    local = {"symbol": "005930.KS", "candles": [{"time": 1, "close": 1.0}], "source": "collector"}
    monkeypatch.setattr(collector_db, "get_daily_candles", AsyncMock(return_value=local))
    monkeypatch.setattr(kmd, "is_enabled", lambda: True)
    kis = AsyncMock(return_value={"symbol": "005930.KS", "candles": [{"time": 2, "close": 2.0}]})
    monkeypatch.setattr(kmd, "get_daily_candles", kis)
    assert asyncio.run(stock.get_candles("005930.KS", "1y", "1d")) is local
    kis.assert_not_awaited()


# 화면 쪽 — 화면 파일은 Figma 결정 뒤에 받는다. 받기 전에 이 시험이 먼저 돈다.
MENU_KEYS_WE_KEEP = ("agent-cb", "agent-products", "agent-news", "indicator-api", "indicator-tradingview")


def test_메뉴에서_우리_화면이_사라지지_않는다():
    """강사님 10-07 판(core.js)은 로보 메뉴에서 셋을 숨기고 인디케이터 둘을 시스템관리로 옮겼다. 지우는 쪽은 충돌 없이
    들어오므로, 시스템관리 쪽 충돌을 우리 판으로 고르면 「증권사 API 자동화」 · 「TradingView 연동」 이 어느 메뉴에도 없게 된다."""
    text = (ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8")
    keys = re.findall(r'^\s*\{\s*key:\s*"([\w-]+)"', text, re.M)
    missing = [k for k in MENU_KEYS_WE_KEEP if k not in keys]
    assert not missing, f"메뉴에서 빠진 화면: {missing}"


def test_rag_답변_엔진_이름이_서버_동작과_맞다():
    """강사님 10-07 판부터 「rag」 모드도 서버 LLM 으로 짧게 요약한다(응답 `llm_used`). 화면 이름이 「LLM 미사용」 이면 틀린
    말이고, 「Qwen」 은 우리 채팅 모델과 다르며 「근거 답 — 법령 · 규정 출처」 와도 헷갈린다 → 「검색 결과 요약」(사용자 10-08)."""
    chat = (ROOT / "app" / "routes" / "chat.py").read_text(encoding="utf-8")
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    agent = (ROOT / "public" / "js" / "agent.js").read_text(encoding="utf-8")
    option = re.search(r'<option value="rag">([^<]*)</option>', html).group(1)
    label = re.search(r'\brag:\s*"([^"]*)"', agent).group(1)
    hint = re.search(r'mode === "rag"\s*\?\s*"([^"]*)"', agent).group(1)   # 입력 칸 안내 글(강사님 판도 옛 글 그대로)
    if "llm_used" in chat:
        assert "LLM 미사용" not in option
        assert "LLM 없이" not in hint, hint
    for text in (option, label):
        assert "Qwen" not in text and "검색 결과 요약" in text, text
