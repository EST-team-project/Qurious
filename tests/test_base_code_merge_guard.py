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
