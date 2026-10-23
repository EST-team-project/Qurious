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
import importlib.util
import inspect
import math
import re
from datetime import date
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
# 10-22 · 10-23 강사님 판은 직접매매 · 미국주식 · 크롤링 메뉴 묶음을 지웠다(3-way 로 충돌 없이 사라짐 — 이슈 #318 3-12) → 묶음째 넣는다.
MENU_KEYS_WE_KEEP = ("agent-cb", "agent-products", "agent-news", "indicator-api", "indicator-tradingview",
                     "trading-chart", "trading-portfolio", "trading-order",
                     "us-dashboard", "us-chart", "us-portfolio", "us-order",
                     "crawl-auto", "crawl-manual", "crawl-ingest")


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


# ── 2026-10-12 th06 5b0a768 1단계 앞 — 지킴이 여섯 ─────────────────────────────────────────────────────
# 강사님 10-08 8커밋(서버 e815be3 → 5b0a768 · 화면 9478811 → 5b0a768)을 받기 전에 쓴다. 조사서
# docs/phase-2/01-analysis/research/기초코드-최신판-융합-조사.md 3절 <표 4> 의 「충돌 표시 없이 바뀌는 곳」 가운데 우리 결정을 지키는 여섯이다.
# 지금 코드에서 통과하고, 저장소 밖 사본에 강사님 판을 한 곳씩 넣으면 실패하는 것을 확인했다(2026-10-12 깨 보기).
# 값을 영원히 묶으려는 것이 아니다 — 바꾸기로 정하면 같은 PR 에서 이 시험 줄을 함께 바꾼다.

BADGE_LINE_RE = re.compile(r'^\s*"?([a-z0-9-]+)"?:\s*A\((\d+),\s*"([^"]+)",', re.M)


def test_배지의_강사님_점수는_점검표와_같다():
    """⑤ 강사님 10-08 판 completion.js 는 지표 비교 45 → 90 · 섹터 인디케이터 42 → 86 으로 올렸다(강사님 판 구현 기준).
    3-way 가 깨끗해 숫자가 말없이 바뀐다. 우리 배지 정본은 점검표 TSV 다(2026-10-04) — 받은 기능은 우리 시험으로 다시 매긴다.
    팀 줄이 덮어 화면에는 안 보여도 강사님 칸은 completion.js 와 같아야 한다 — 강사님 표가 바뀌면 점검표 강사님 칸을 먼저 고친다
    (2026-10-12 — 이동원 몫 줄이 모두 배지반영 「예」 가 되어 「아니오」 줄만 보면 볼 줄이 0 이었다 · 팀 줄의 점수는 TC-CP 가 본다).
    팀원 화면은 팀 결정 전이라 이동원 · 주인 없는(—) 줄만 본다(TC-CP 와 같은 까닭 — 팀원 PR 이 실패하지 않게)."""
    import csv

    src = (ROOT / "public" / "js" / "completion.js").read_text(encoding="utf-8")
    start = src.index("const ASSESSMENTS = {")
    badge = {m.group(1): (int(m.group(2)), m.group(3))
             for m in BADGE_LINE_RE.finditer(src[start:src.index("\n};", start)])}
    with (ROOT / "docs" / "phase-3" / "04-testing" / "대장" / "기능완성도-점검표.tsv").open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f, delimiter="\t")
                if r["강사님"].strip()
                and (r["주담당"] == "—" or r["주담당"].startswith("이동원"))]
    assert rows, "점검표에서 볼 줄을 하나도 못 찾았다 — 칸 이름 · 값을 볼 것"
    for r in rows:
        key = r["화면키"]
        assert key in badge, f"{key}: completion.js 에 줄이 없다"
        assert badge[key] == (int(r["강사님"]), r["강사님_이름표"]), \
            f"{key}: 배지 {badge[key]} ↔ 점검표 강사님 칸 {r['강사님']} {r['강사님_이름표']} — 점검표를 먼저 고친다"


# 글꼴 · 아이콘처럼 지금 쓰는 CDN. 새 바깥 CSS 는 까닭과 함께 여기에 더한다.
STYLE_HOSTS_ALLOWED = frozenset({"cdn.jsdelivr.net", "cdnjs.cloudflare.com"})


def test_html_넷에_바깥_공통_CSS_링크가_없다():
    """⑥ 강사님 10-08 판은 html 넷(index · login · register · app)에 강사님 도메인의 공통 CSS 한 줄을 넣었다
    (`https://www.edumgt.co.kr/css/common.css`). 런타임에 바깥 주소를 읽고, 그 CSS 가 모든 footer 를 높이 25px · 한 줄 ·
    넘치면 잘림(`!important`)으로 묶어 우리 푸터의 투자 권유 고지가 폭에 따라 잘린다(Q3 — 받지 않음 · 2026-10-12).
    허용 목록 밖 호스트의 stylesheet 링크와 CSS 파일의 바깥 `@import` 를 함께 본다."""
    from urllib.parse import urlparse

    found = []
    for page in ("index.html", "login.html", "register.html", "app.html"):
        html = (ROOT / "public" / page).read_text(encoding="utf-8")
        for tag in re.findall(r"<link\b[^>]*>", html, re.I):
            href = re.search(r'href\s*=\s*"([^"]+)"', tag, re.I)
            if not href or not re.search(r'rel\s*=\s*"[^"]*stylesheet', tag, re.I):
                continue
            host = urlparse(href.group(1)).netloc
            if host and host not in STYLE_HOSTS_ALLOWED:
                found.append(f"{page}: {tag}")
    for css in (ROOT / "public" / "css").glob("*.css"):
        for m in re.finditer(r"@import\s+(?:url\()?\s*['\"]?(https?:)?//", css.read_text(encoding="utf-8")):
            found.append(f"{css.name}: {m.group(0)}")
    assert not found, "허용 목록 밖 바깥 CSS:\n" + "\n".join(found)


def test_html_넷에_글자_줄이기_스크립트가_없다():
    """강사님 10-22 판(`7652de8`)은 html 넷(index · login · register · app)에 `compact-typography.js` 를 넣었다 — 모든 화면의
    글자 크기 · 줄 간격을 실행 중에 줄이는 스크립트라, 들어오면 우리 화면(차트 이름표 · 표 · 푸터 고지)의 크기가 Figma 시안과
    달라진다(이슈 #318 3-12 · 받지 않음). 줄 하나만 더해지는 변경이라 3-way 에서 충돌 없이 들어온다."""
    found = [page for page in ("index.html", "login.html", "register.html", "app.html")
             if "compact-typography" in (ROOT / "public" / page).read_text(encoding="utf-8")]
    assert not found, f"글자 줄이기 스크립트가 들어온 html: {found}"
    assert not (ROOT / "public" / "js" / "compact-typography.js").exists()


FOOTER_NOTICE = "투자 자문이 아닌 정보 제공 목적입니다."


def test_푸터에_투자_권유_고지가_있고_높이를_묶는_규칙이_없다():
    """⑥ 강사님 10-08 판 app.html 은 푸터를 「© 2026 (주)에듀엠지티 All rights reserved.」 한 줄로 바꿔 고지를 지웠고,
    공통 CSS 는 footer 를 `height: 25px !important` 로 묶는다. 고지 글은 브랜드 한 곳(brand.js)이 정본이고 푸터 자리가 그 글을 싣는다."""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    footer = re.search(r'<footer id="app-footer">(.*?)</footer>', html, re.S)
    assert footer, "app.html 에 우리 푸터(#app-footer)가 없다"
    assert 'data-brand="notice"' in footer.group(1) and FOOTER_NOTICE in footer.group(1)
    assert f'notice: "{FOOTER_NOTICE}"' in (ROOT / "public" / "js" / "brand.js").read_text(encoding="utf-8")
    pinned = []
    for css in (ROOT / "public" / "css").glob("*.css"):
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css.read_text(encoding="utf-8")):
            if "footer" in selector and re.search(r"(?<![-\w])height\s*:\s*[\d.]+px\s*!important", body):
                pinned.append(f"{css.name}: {selector.strip()}")
    assert not pinned, f"푸터 높이를 !important 로 묶는 규칙: {pinned}"


CYCLE_TEXT_FILES = ("public/js/core.js", "public/js/dashboard.js", "public/app.html")
CYCLE_PHRASE = re.compile(r"(\d+)\s*분\s*(?:주기|마다|사이클)|주기\s*\(\s*기본\s*(\d+)\s*분\s*\)|사이클\s*\(\s*(\d+)\s*분\s*\)")
CYCLE_CONTEXT = re.compile(r"매매|시그널|사이클|auto_trade")


def test_화면_안내의_자동매매_주기_문구는_설정값이다():
    """⑩ 강사님 10-08 판 core.js 는 충돌 밖 줄에 「정해진 주기(기본 3분)」 · 「3분 주기」 를 싣는다(강사님 주기 180초).
    위 `test_자동매매_주기는_600초다` 는 설정만 보므로 화면 문구는 못 잡는다. 같은 줄에 자동매매 문맥(매매 · 시그널 · 사이클)이
    있는 「N분 주기 · N분마다 · 주기(기본 N분) · 사이클(N분)」 만 센다 — 체결 확인 2분 · 리밸런싱 준비 5분 같은 다른 주기는 세지 않는다."""
    minutes = _default("QUANT_CYCLE_SEC") // 60
    seen, wrong = 0, []
    for rel in CYCLE_TEXT_FILES:
        for no, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            if not CYCLE_CONTEXT.search(line):
                continue
            for m in CYCLE_PHRASE.finditer(line):
                seen += 1
                if int(next(g for g in m.groups() if g)) != minutes:
                    wrong.append(f"{rel}:{no}: 「{m.group(0)}」")
    assert seen, "자동매매 주기 문구를 하나도 못 찾았다 — 문구 꼴이 바뀌었는지 볼 것"
    assert not wrong, f"설정({minutes}분)과 다른 주기 문구:\n" + "\n".join(wrong)


def test_게이트웨이_없이도_한글_종목_검색_결과가_있다(monkeypatch):
    """① 강사님 10-08 판 종목 검색은 1차 소스를 KRX 상장법인목록에서 바깥 OHLCV 저장소(stock-coin-trade 게이트웨이)로 바꾸고,
    찾은 종목을 검색 중에 저장소에 적재한다. 게이트웨이가 없으면 저장소 단계가 비고, 야후 자동완성은 「카카오」 같은 한글
    검색어에 400 을 주어 결과가 빈다(회귀). 우리 판은 KRX 상장법인목록을 먼저 본다(Q2 — 유지 · 2026-10-12)."""
    from unittest.mock import AsyncMock

    import httpx

    from app.config import settings
    from app.routes import stocks as stocks_route
    from app.services import krx_companies

    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "")
    listing = [{"name": "카카오게임즈", "code": "293490", "market": "코스닥", "symbol": "293490.KQ"},
               {"name": "카카오", "code": "035720", "market": "코스피", "symbol": "035720.KS"}]
    monkeypatch.setattr(krx_companies, "get_krx_companies", AsyncMock(return_value=listing))

    async def _no_network(*_a, **_k):
        raise AssertionError("한글 종목 검색이 바깥(야후 · 게이트웨이)으로 나갔다")

    monkeypatch.setattr(httpx.AsyncClient, "send", _no_network)
    out = asyncio.run(stocks_route.stock_search("카카오"))
    assert [r["symbol"] for r in out["results"]] == ["035720.KS", "293490.KQ"], out


def _calls_with_guards(path: Path, name: str) -> list[tuple[int, int, list[str]]]:
    """파일에서 `name(...)` · `x.name(...)` 부름마다 (줄, 인자 수, 둘러싼 if 조건 글들) — else 갈래는 조건을 더하지 않는다."""
    out: list[tuple[int, int, list[str]]] = []

    def walk(node: ast.AST, conds: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = conds + [ast.unparse(node.test)] if isinstance(node, ast.If) and child in node.body else conds
            if isinstance(child, ast.Call):
                fn = child.func
                if (fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)) == name:
                    out.append((child.lineno, len(child.args) + len(child.keywords), inner))
            walk(child, inner)

    walk(ast.parse(path.read_text(encoding="utf-8")), [])
    return out


# 사용자 행 없이 경로를 잡아도 되는 곳 — 계정 무관 KIS 모의투자 시스템 배치(강사님 10-06 · 2026-10-08 받음)뿐이다.
SYSTEM_ROUTE_CALLERS = frozenset({"app/services/kis_batch.py"})


def test_사용자_주문은_그_사용자_키로만_경로를_잡는다():
    """④ 강사님 10-08 판 auto_trade.place_manual_kis_order(화면에서 내는 KIS 모의 주문)는 `resolve_route()` 를 사용자 행 없이
    부르고, 게이트웨이가 없으면 서버 계좌 `kis_credentials.get_credentials()` 를 읽는다. 우리 판(ADR-0004 · 키는 사용자마다)에서는
    게이트웨이가 없으면 늘 「연동 안 됨」 으로 막히고, 게이트웨이가 있으면 모든 사용자가 서버 계좌 하나로 주문한다.
    3-way 가 이 함수를 충돌 없이 들여오므로 코드 전체에서 두 규칙을 본다(받을지는 주담당 이슈 B1).
      ① KIS 경로 해석 `resolve_route` 는 사용자 행을 넘겨 부른다 — 인자 없이는 시스템 배치만
      ② 서버 계좌 `get_credentials()` 는 `is_managed(...)` 갈래 안에서만 — 우리 판은 그 갈래가 비어 늘 사용자 키로 간다"""
    no_row, server_account = [], []
    for path in _app_python_files():
        rel = path.relative_to(ROOT).as_posix()
        for line, nargs, _conds in _calls_with_guards(path, "resolve_route"):
            if nargs == 0 and rel not in SYSTEM_ROUTE_CALLERS:
                no_row.append(f"{rel}:{line}")
        if rel == "app/services/kis_credentials.py":
            continue
        for line, _nargs, conds in _calls_with_guards(path, "get_credentials"):
            if not any("is_managed(" in c for c in conds):
                server_account.append(f"{rel}:{line}")
    assert not no_row, "사용자 행 없이 KIS 경로를 잡는 곳:\n" + "\n".join(no_row)
    assert not server_account, "is_managed 갈래 밖에서 서버 계좌를 읽는 곳:\n" + "\n".join(server_account)


def test_전략_분석_비교에_추가_속성은_괄호_뒤에서_닫힌다():
    """2026-10-13 · 강사님 `3a135b1` 과 같은 고침 — `onclick='compareTrayAdd(${…})'>`(괄호 → 작은따옴표 → >) 차례.
    옛 꼴 `}')">` 은 속성 값이 괄호 앞에서 끊겨 누르면 SyntaxError 다(node 재현). 강사님 최신을 받을 때 옛 꼴로 되돌아가지 않게 지킨다 —
    성과 검증(`indicator.js` · 신장환 님 화면)의 같은 꼴은 이슈로 알렸다."""
    src = (ROOT / "public" / "js" / "quant.js").read_text(encoding="utf-8")
    assert "}')\">⚖️ 비교에 추가" not in src
    assert src.count("})'>⚖️ 비교에 추가") == 1


# ── 강사님 th06 새 10커밋(`8624e81..ebf4668`) 지킴이 넷 + 가져오기 1차 지킴이 (2026-10-22 · D78) ─────────────
# 넷은 10-13 배경 조사(docs/phase-2/01-analysis/research/배경조사/2026-10-13-강사님기초코드-새10커밋/결과.md 3절 7번)가
# 고른 것이다. 모두 3-way 가 충돌 표시 없이 들여오는 줄이라, 강사님 최신을 받기 전에 먼저 돌린다.


def test_기업_대시보드가_부르는_불러오기_함수가_정의돼_있다():
    """① 🔴 R1 — 강사님 `c66fa00` 은 통화 단위를 고치며 `fetchAndRenderCompany` 정의를 지웠다. 부르는 곳 둘(`loadCompanyDashboard` ·
    `selectCompany`)은 남아서 강사님 `ebf4668` 판은 기업 대시보드를 열면 `ReferenceError` 다(node 재현). 우리 기준으로 3-way 해도
    충돌 0 으로 같은 결과가 된다 → 부르는 이름이 정의돼 있는지, 받아 온 자료를 그리는 함수가 실제로 불리는지 본다."""
    src = (ROOT / "public" / "js" / "company.js").read_text(encoding="utf-8")
    defined = set(re.findall(r"^(?:async\s+)?function\s+(\w+)\s*\(", src, flags=re.M))
    assert "fetchAndRenderCompany" in defined, "company.js 에 fetchAndRenderCompany 정의가 없다(c66fa00 꼴)"
    callers = re.findall(r"(?<!function )(?<![\w.])fetchAndRenderCompany\s*\(", src)
    assert len(callers) >= 2, "불러오기를 부르는 곳(목록 열기 · 회사 고르기)이 사라졌다"
    assert re.search(r"(?<!function )(?<![\w.])renderCompanyData\s*\(", src), "renderCompanyData 를 부르는 곳이 0 — 받은 자료를 그리지 않는다"


def test_LEAN_백테스트_종가는_수정_종가다(monkeypatch):
    """② 🟡 Y1 — 강사님 `2852210` 은 `fetch_close_series` 를 야후 `adjclose`(수정 종가) → 바깥 일봉 저장소의 원시 종가로 바꿨다.
    우리 파일이 그 직전 판과 같아 말없이 들어온다. 원시 종가는 분할 · 배당락 계단을 손실로 잡아 수익률 · MDD 가 틀어진다
    → 수정 종가와 원시 종가가 함께 오면 수정 종가를 쓰는지 본다(원천을 바꿀지는 주담당 몫 · 받을 때는 이슈로)."""
    from app.services import lean_backtest

    payload = {"chart": {"result": [{
        "timestamp": [1767312000, 1767398400, 1767484800],
        "indicators": {"quote": [{"close": [200.0, 100.0, 102.0]}],          # 둘째 날 1:2 분할 — 원시 종가는 반 토막
                       "adjclose": [{"adjclose": [100.0, 100.0, 102.0]}]},
    }]}}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr(lean_backtest.httpx, "AsyncClient", _Client)
    series = asyncio.run(lean_backtest.fetch_close_series("TEST", date(2026, 1, 2), date(2026, 1, 4)))
    assert list(series.values) == [100.0, 100.0, 102.0], "분할 계단(200 → 100)이 종가에 들어왔다 — 원시 종가를 쓴다"
    assert not {"daily_candles", "ohlcv_store"} & _code_names(lean_backtest)


def _used_names(module) -> set[str]:
    """모듈이 import 하거나 부르는 이름 전부(모듈 경로 · import 한 이름 · 변수 · 속성) — 주석 · 독스트링은 세지 않는다."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_일봉은_바깥_OHLCV_저장소를_먼저_읽지_않는다():
    """③ 🟡 Y2 — 강사님 `2852210` 은 `OHLCV_STORE_FIRST = True` 와 `stock.get_candles` 훅으로 일봉을 강사님 서버 저장소
    (`/openapi/v1/ohlcv/{code}` · 없으면 `ingest` POST)에서 먼저 읽는다. 우리 일봉 정본은 수집 DB(DF-08)라 받지 않기로 했다(F17 ④)
    — 설정 깃발 · 저장소 모듈 · 시세 서비스의 호출 셋 모두 없어야 한다."""
    from app.config import settings
    from app.services import stock

    assert not hasattr(settings, "OHLCV_STORE_FIRST")
    assert importlib.util.find_spec("app.services.ohlcv_store") is None
    assert not [name for name in _used_names(stock) if "ohlcv_store" in name]


def _fixed_candles(n: int = 120) -> list[dict]:
    """정해진 시계열(사인 + 완만한 오름 · 2026-01-02 부터 하루 한 봉) — 점수 식이 바뀌었는지만 보려는 것이라 값에 뜻은 없다."""
    out, prev = [], 100.0
    for i in range(n):
        close = 100 + 10 * math.sin(i / 7) + 0.2 * i
        out.append({"time": 1767312000 + i * 86400, "open": round(prev, 2), "high": round(max(prev, close) + 1, 2),
                    "low": round(min(prev, close) - 1, 2), "close": round(close, 2), "volume": 1000 + i * 10})
        prev = close
    return out


# 정의 이름마다 위 시계열의 (타임프레임 점수 · 근거 · 패턴 점수 · 쏠림 · 캔들 패턴 · 돌파) — 식을 바꾸면 정의를 올리고 한 줄 더한다
PINNED_SIGNAL_SCORES = {
    "tv-2026": (-1, ["RSI 24 과매도", "MA5 < MA20 하락 배열", "MACD < 시그널", "20MA 아래 (추세 비우호)"],
                -1.0, "bearish", [], [("breakdown_20d", False)]),
}


def test_신호_점수_식이_바뀌면_정의_이름도_바뀐다():
    """④ 🟡 — 강사님 `46da4cc` 은 패턴 분석을 넓히며 타임프레임 점수 범위를 ±6 → ±7 로 바꿨다. 그대로 받으면 매일 쌓는 다중 주기
    신호(정의 `tv-2026`)의 뜻이 기록 중간에 바뀌어 날짜끼리 견줄 수 없다. 정해진 시계열 하나의 점수 · 근거를 고정해 두고,
    식이 바뀌면 `ta_utils.DEFINITION` 도 함께 올리게 한다."""
    from app.services import patterns, ta_utils

    candles = _fixed_candles()
    tf, ps = patterns.timeframe_score(candles), patterns.pattern_summary(candles)
    got = (tf["score"], tf["reasons"], ps["pattern_score"], ps["pattern_bias"],
           [(p["key"], p["bars_ago"]) for p in ps["patterns"]],
           [(b["key"], b.get("confirmed")) for b in ps["breakouts"]])
    assert ta_utils.DEFINITION in PINNED_SIGNAL_SCORES, f"정의 {ta_utils.DEFINITION} 의 고정값을 PINNED_SIGNAL_SCORES 에 더하세요"
    assert got == PINNED_SIGNAL_SCORES[ta_utils.DEFINITION], \
        "같은 정의 이름인데 점수 식이 바뀌었다 — ta_utils.DEFINITION 을 올리고 새 고정값을 한 줄 더하세요"


def _settings_writes(path: Path) -> list[int]:
    """설정 객체(`settings`)에 값을 쓰는 줄 — `setattr(settings, …)` · `settings.X = …` · `settings.X += …`."""
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setattr" and node.args \
                and getattr(node.args[0], "id", None) == "settings":
            lines.append(node.lineno)
        targets = node.targets if isinstance(node, ast.Assign) else \
            [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else []
        lines += [node.lineno for t in targets
                  if isinstance(t, ast.Attribute) and getattr(t.value, "id", None) == "settings"]
    return lines


def test_앱_코드는_실행_중에_설정_객체를_바꾸지_않는다():
    """⑤ G1 — 강사님 전략설정(`app/services/strategy_settings.py:230`)은 저장할 때 `setattr(settings, …)` 로 프로세스 전체 설정을
    바꾼다. 한 계정의 저장이 모든 계정의 자동매매에 걸린다(우리는 사용자마다 · ADR-0004). 가져오기 1차(2026-10-22)는 이 줄을 막고
    본인 설정 저장까지만 받는다 — 앱 코드 어디서든(`app/config.py` 밖) 설정 객체에 값을 쓰는 줄이 없어야 한다."""
    found = [f"{path.relative_to(ROOT).as_posix()}:{line}"
             for path in _app_python_files() if path.relative_to(ROOT).as_posix() != "app/config.py"
             for line in _settings_writes(path)]
    assert not found, "설정 객체에 값을 쓰는 곳(프로세스 전체 · 모든 계정에 걸림):\n" + "\n".join(found)


def test_올린_문서는_문지기로만_읽고_쓴다():
    """DF-146(2026-10-23) — 올린 문서는 사용자 비공개 모음에만 있고, 그 모음은 app/services/user_docs.py 만 연다.
    강사님 판은 올린 문서를 공용 모음(`DOCUMENT_COLLECTION = "fin_chunks"`)에 넣고 채팅 · 문서 검색이 거르지 않는다 —
    3-way 병합으로 그 줄들이 충돌 없이 되돌아오면 남의 문서가 다시 보인다."""
    app_dir = ROOT / "app"
    literal = re.compile(r"[\"']user_docs[\"']")
    owners = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in app_dir.rglob("*.py")
                    if literal.search(p.read_text(encoding="utf-8")))
    assert owners == ["app/services/user_docs.py"], f"비공개 모음 이름이 문지기 밖에 있다: {owners}"
    docs = (app_dir / "routes" / "documents.py").read_text(encoding="utf-8")
    for old in ("DOCUMENT_COLLECTION", "rag_search", "store_chunks", "delete_chunks_by_source"):
        assert old not in docs, f"documents.py 가 공용 모음 길({old})을 다시 쓴다"
    for call in ('user_docs.store(user["id"]', 'user_docs.search(user["id"]', 'user_docs.delete_doc(user["id"]'):
        assert call in docs, f"documents.py 가 문지기를 거치지 않는다: {call}"
    chat = (app_dir / "routes" / "chat.py").read_text(encoding="utf-8")
    assert not re.search(r"\brag_search\(", chat), "chat.py 가 공용 검색만 부른다(내 문서가 빠지고 거름 규칙이 흩어진다)"
    assert chat.count("search_with_shared(body.question, owner_id=user_id") == 2
    rag = (app_dir / "services" / "rag_pipeline.py").read_text(encoding="utf-8")
    assert "filter=shared_filter(filter_source)" in rag and "USER_DOCS_COLLECTION" in rag
    auth = (app_dir / "routes" / "auth.py").read_text(encoding="utf-8")
    assert 0 < auth.index("user_docs.delete_owner(") < auth.index("account.delete_user_data(db, uid)"),         "탈퇴가 벡터 조각보다 DB 를 먼저 지운다(조각이 남는다)"


def test_그래프_라우터는_로그인한_사람만():
    """DF-146 조사 곁가지 ①(2026-10-23) — 강사님 판의 /api/graph 라우터에는 로그인이 없어, 로그인 안 한 사람도 벡터 조각을
    읽고 그래프를 다시 채울(/seed) 수 있었다 → 라우터 전체는 로그인한 사람 · /seed 는 관리자."""
    graph = (ROOT / "app" / "routes" / "graph.py").read_text(encoding="utf-8")
    assert re.search(r"APIRouter\([^)]*dependencies=\[Depends\(get_current_user_any\)\]", graph)
    assert '@router.post("/seed", dependencies=[Depends(require_roles("admin"))])' in graph

